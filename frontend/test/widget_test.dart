import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/app/nxtrep_app.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/app_loading_page.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';

class _MemoryRefreshTokenStore implements RefreshTokenStore {
  String? value;

  @override
  Future<void> delete() async => value = null;

  @override
  Future<String?> read() async => value;

  @override
  Future<void> write(String token) async => value = token;
}

void main() {
  test('session restores account settings and clears them on logout', () async {
    final store = _MemoryRefreshTokenStore()..value = 'refresh';
    final tokens = SessionTokens(store);
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://test/api/v1')),
      accessTokenProvider: () => tokens.accessToken,
      httpClient: MockClient((request) async {
        final body = switch (request.url.path) {
          '/api/v1/auth/refresh' => {
            'access_token': 'access',
            'refresh_token': 'next',
            'token_type': 'bearer',
            'expires_in': 3600,
            'refresh_expires_in': 7200,
            'user': {
              'id': 'u',
              'username': 'tester',
              'password_setup_required': false,
            },
          },
          '/api/v1/me' => {
            'id': 'u',
            'username': 'tester',
            'status': 'active',
            'is_admin': false,
            'password_setup_required': false,
            'profile_initialized': true,
          },
          '/api/v1/settings' => {
            'unit_system': 'imperial',
            'timezone': 'Asia/Shanghai',
            'privacy_mode': 'summary',
            'share_anonymous_analytics': false,
            'version': 3,
          },
          '/api/v1/auth/logout' => null,
          _ => throw StateError('unexpected request'),
        };
        return body == null
            ? http.Response('', 204)
            : http.Response(jsonEncode(body), 200);
      }),
    );
    final session = SessionController(
      authRepository: AuthRepository(apiClient: api, tokens: tokens),
      onboardingRepository: OnboardingRepository(api),
    );
    addTearDown(session.dispose);
    addTearDown(api.close);
    await session.initialize();
    expect(session.phase, SessionPhase.authenticated);
    expect(session.appSettings?.unitSystem, 'imperial');
    expect(session.appSettings?.privacyMode, 'summary');
    await session.logout();
    expect(session.phase, SessionPhase.signedOut);
    expect(session.appSettings, isNull);
  });

  testWidgets(
    'shows loading during restore and preserves rejected login input',
    (tester) async {
      final store = _MemoryRefreshTokenStore()..value = 'stored-refresh-token';
      final tokens = SessionTokens(store);
      final refresh = Completer<http.Response>();
      final login = Completer<http.Response>();
      final client = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => tokens.accessToken,
        httpClient: MockClient(
          (request) => switch (request.url.path) {
            '/api/v1/auth/refresh' => refresh.future,
            '/api/v1/auth/login' => login.future,
            _ => throw StateError('unexpected request'),
          },
        ),
      );
      final auth = AuthRepository(apiClient: client, tokens: tokens);
      client.tokenRefresher = auth.refreshSession;
      final session = SessionController(
        authRepository: auth,
        onboardingRepository: OnboardingRepository(client),
      );

      await tester.pumpWidget(
        NxtRepApp(sessionController: session, onDispose: client.close),
      );
      expect(find.byType(AppLoadingPage), findsOneWidget);
      expect(find.text('NxtRep'), findsOneWidget);

      refresh.complete(http.Response('{}', 401));
      await tester.pumpAndSettle();
      expect(find.byType(AppLoadingPage), findsNothing);
      await tester.enterText(find.byType(TextFormField).first, 'loading-user');
      await tester.enterText(
        find.byType(TextFormField).last,
        'not-a-real-password',
      );
      await tester.ensureVisible(find.text('登录'));
      await tester.tap(find.text('登录'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byType(AppLoadingPage), findsOneWidget);

      login.complete(
        http.Response(
          '{"error":{"code":"INVALID_CREDENTIALS","message":"Invalid"}}',
          401,
          headers: {'content-type': 'application/json'},
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(AppLoadingPage), findsNothing);
      expect(find.text('用户名或密码不正确'), findsOneWidget);
      final fields = tester.widgetList<TextFormField>(
        find.byType(TextFormField),
      );
      expect(fields.first.controller?.text, 'loading-user');
      expect(fields.last.controller?.text, 'not-a-real-password');
      expect(
        tester.widget<FilledButton>(find.byType(FilledButton)).onPressed,
        isNotNull,
      );
    },
  );

  testWidgets('shows login when there is no stored session', (tester) async {
    final tokens = SessionTokens(_MemoryRefreshTokenStore());
    final client = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => tokens.accessToken,
      httpClient: MockClient(
        (_) async => throw StateError('unexpected request'),
      ),
    );
    final auth = AuthRepository(apiClient: client, tokens: tokens);
    client.tokenRefresher = auth.refreshSession;
    final session = SessionController(
      authRepository: auth,
      onboardingRepository: OnboardingRepository(client),
    );

    await tester.pumpWidget(
      NxtRepApp(sessionController: session, onDispose: client.close),
    );
    await tester.pumpAndSettle();

    expect(find.text('NxtRep'), findsOneWidget);
    expect(find.text('登录'), findsOneWidget);
    expect(find.text('用户名'), findsOneWidget);
  });
}

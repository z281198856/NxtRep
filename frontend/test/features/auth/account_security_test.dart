import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/api_exception.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/auth_models.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/account_security_controller.dart';
import 'package:nxtrep/features/auth/presentation/account_security_page.dart';

class _Store implements RefreshTokenStore {
  String? value;
  bool failWrite = false;
  @override
  Future<void> delete() async => value = null;
  @override
  Future<String?> read() async => value;
  @override
  Future<void> write(String token) async {
    if (failWrite) throw StateError('platform storage unavailable');
    value = token;
  }
}

Map<String, Object> _pair(String suffix) => {
  'access_token': 'access-$suffix',
  'refresh_token': 'refresh-$suffix',
  'token_type': 'bearer',
  'expires_in': 900,
  'refresh_expires_in': 86400,
  'user': {'id': 'user', 'username': 'test', 'password_setup_required': false},
};

class _Fixture {
  final store = _Store();
  late final tokens = SessionTokens(store);
  late final api = ApiClient(
    config: ApiConfig(baseUri: Uri.parse('https://test/api/v1')),
    accessTokenProvider: () => tokens.accessToken,
    httpClient: MockClient(_handle),
  );
  late final repository = AuthRepository(apiClient: api, tokens: tokens);
  late final controller = AccountSecurityController(
    repository,
    onRequireLogin: (message) async {
      requireLoginMessages.add(message);
      await repository.clearLocalSession();
    },
  );
  final requests = <http.Request>[];
  final requireLoginMessages = <String>[];
  final passwordStarted = Completer<void>();
  Completer<void>? passwordGate;
  int passwordStatus = 200;
  ApiException? passwordError;
  var remaining = <String>['current', 'other'];

  Future<void> prepare() async {
    await tokens.replace(TokenPair.fromJson(_pair('old')));
    api.tokenRefresher = repository.refreshSession;
    addTearDown(controller.dispose);
    addTearDown(api.close);
  }

  http.Response response(Object value, [int status = 200]) => http.Response(
    jsonEncode(value),
    status,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
  Future<http.Response> _handle(http.Request request) async {
    requests.add(request);
    final path = request.url.path;
    if (path.endsWith('/auth/sessions')) {
      return response({
        'sessions': [
          for (final id in remaining)
            {
              'id': id,
              'device_name': 'Android 设备',
              'created_at': '2026-11-01T00:00:00Z',
              'expires_at': '2026-12-01T00:00:00Z',
              'last_used_at': '2026-11-01T01:00:00Z',
              'is_current': id == 'current',
            },
        ],
      });
    }
    if (path.endsWith('/auth/password/change')) {
      if (!passwordStarted.isCompleted) passwordStarted.complete();
      if (passwordGate != null) await passwordGate!.future;
      if (passwordError case final error?) throw error;
      if (passwordStatus == 401) {
        return response({
          'error': {
            'code': 'INVALID_CURRENT_PASSWORD',
            'message': 'invalid password',
          },
        }, 401);
      }
      remaining = ['current'];
      return response(_pair('new'));
    }
    if (path.endsWith('/auth/refresh')) return response(_pair('renewed'));
    if (path.endsWith('/sessions/revoke-others')) {
      remaining = ['current'];
      return http.Response('', 204);
    }
    if (request.method == 'DELETE' && path.contains('/auth/sessions/')) {
      remaining.remove(path.split('/').last);
      return http.Response('', 204);
    }
    throw StateError('Unexpected security endpoint');
  }

  Future<void> mount(WidgetTester tester) async {
    await prepare();
    await tester.pumpWidget(
      MaterialApp(home: AccountSecurityPage(controller: controller)),
    );
    await tester.pumpAndSettle();
  }
}

void main() {
  test(
    'wrong current password does not refresh tokens or end the login',
    () async {
      final state = _Fixture()..passwordStatus = 401;
      await state.prepare();
      expect(
        await state.controller.changePassword('wrong', 'next-password'),
        isFalse,
      );
      expect(state.controller.errorMessage, '当前密码不正确，请重新输入');
      expect(state.tokens.accessToken, 'access-old');
      expect(state.requireLoginMessages, isEmpty);
      expect(
        state.requests.where((r) => r.url.path.endsWith('/auth/refresh')),
        isEmpty,
      );
    },
  );

  test('concurrent refresh waits for password token rotation and uses the new secret', () async {
    final state = _Fixture()..passwordGate = Completer<void>();
    await state.prepare();
    final change = state.repository.changePassword(
      currentPassword: 'current-password',
      newPassword: 'next-password',
    );
    await state.passwordStarted.future;
    final refresh = state.repository.refreshSession();
    await Future<void>.delayed(Duration.zero);
    expect(
      state.requests.where((r) => r.url.path.endsWith('/auth/refresh')),
      isEmpty,
    );
    state.passwordGate!.complete();
    await change;
    expect(await refresh, isTrue);
    final request = state.requests.singleWhere(
      (r) => r.url.path.endsWith('/auth/refresh'),
    );
    expect((jsonDecode(request.body) as Map)['refresh_token'], 'refresh-new');
    expect(state.tokens.accessToken, 'access-renewed');
    expect(state.store.value, 'refresh-renewed');
  });

  test(
    'uncertain password result clears local login without repeating the change',
    () async {
      final state = _Fixture()
        ..passwordError = const ApiException(
          code: 'REQUEST_TIMEOUT',
          message: 'timeout',
        );
      await state.prepare();
      expect(
        await state.controller.changePassword(
          'current-password',
          'next-password',
        ),
        isFalse,
      );
      expect(state.requireLoginMessages.single, contains('结果暂时无法确认'));
      expect(state.tokens.accessToken, isNull);
      expect(state.store.value, isNull);
      expect(
        state.requests
            .where((r) => r.url.path.endsWith('/auth/password/change'))
            .length,
        1,
      );
    },
  );

  test('a successful password change with storage failure requires the new password to log in', () async {
    final state = _Fixture();
    await state.prepare();
    state.store.failWrite = true;
    expect(
      await state.controller.changePassword(
        'current-password',
        'next-password',
      ),
      isFalse,
    );
    expect(state.requireLoginMessages.single, contains('使用新密码重新登录'));
    expect(state.tokens.accessToken, isNull);
  });

  test(
    'unverified current device response cannot enable destructive actions',
    () async {
      final state = _Fixture()..remaining = ['other'];
      await state.prepare();
      await state.controller.refresh();
      expect(state.controller.sessions, isEmpty);
      expect(state.controller.errorMessage, contains('状态不完整'));
    },
  );

  testWidgets(
    'current device is server identified; cancelling and confirming another device are distinct',
    (tester) async {
      final state = _Fixture();
      await state.mount(tester);
      expect(find.text('当前设备'), findsOneWidget);
      expect(find.text('退出该设备'), findsOneWidget);
      expect(find.byKey(const ValueKey('revoke-current')), findsNothing);
      await tester.ensureVisible(find.text('退出该设备'));
      await tester.tap(find.text('退出该设备'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();
      expect(state.requests.where((r) => r.method == 'DELETE'), isEmpty);
      await tester.tap(find.text('退出该设备'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('确认退出'));
      await tester.pumpAndSettle();
      expect(
        state.requests.singleWhere((r) => r.method == 'DELETE').url.path,
        endsWith('/sessions/other'),
      );
      expect(find.text('当前设备'), findsOneWidget);
      expect(find.text('目前只有当前设备保持登录。'), findsOneWidget);
    },
  );

  testWidgets(
    'bulk device exit keeps the current session and uses the explicit endpoint',
    (tester) async {
      final state = _Fixture()..remaining = ['current', 'other', 'third'];
      await state.mount(tester);
      await tester.scrollUntilVisible(find.text('退出其他所有设备'), 200);
      await tester.tap(find.text('退出其他所有设备'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('确认退出'));
      await tester.pumpAndSettle();
      expect(
        state.requests
            .where((r) => r.url.path.endsWith('/sessions/revoke-others'))
            .length,
        1,
      );
      expect(find.text('当前设备'), findsOneWidget);
      expect(state.controller.otherCount, 0);
    },
  );

  testWidgets(
    'password validation, wrong password and successful token replacement keep correct state',
    (tester) async {
      final state = _Fixture()..passwordStatus = 401;
      await state.mount(tester);
      await tester.tap(find.text('修改密码'));
      await tester.pumpAndSettle();
      Future<void> fill(String key, String text) async {
        final field = find.byKey(ValueKey('password-$key'));
        await tester.ensureVisible(field);
        await tester.enterText(field, text);
      }

      Future<void> submit() async {
        await tester.ensureVisible(find.text('确认修改密码'));
        await tester.tap(find.text('确认修改密码'));
        await tester.pumpAndSettle();
      }

      await fill('current', 'current-password');
      await fill('next', 'short');
      await fill('repeat', 'different');
      await submit();
      expect(state.requests.where((r) => r.method == 'POST'), isEmpty);
      await fill('next', 'next-password');
      await fill('repeat', 'next-password');
      await submit();
      expect(find.text('当前密码不正确，请重新输入'), findsOneWidget);
      expect(state.requireLoginMessages, isEmpty);
      state.passwordStatus = 200;
      await fill('current', 'current-password');
      await submit();
      expect(find.text('账户安全'), findsOneWidget);
      expect(state.tokens.accessToken, 'access-new');
      expect(state.store.value, 'refresh-new');
      expect(state.controller.otherCount, 0);
      expect(find.byType(TextFormField), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}

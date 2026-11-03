import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nxtrep/app/nxtrep_app.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/api_exception.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/presentation/account_security_page.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  testWidgets(
    'account security: device controls, password change and revoked-session navigation',
    (tester) async {
      const username = String.fromEnvironment('E2E_USERNAME');
      const password = String.fromEnvironment('E2E_PASSWORD');
      const nextPassword = String.fromEnvironment('E2E_NEXT_PASSWORD');
      expect(
        username.isNotEmpty && password.isNotEmpty && nextPassword.isNotEmpty,
        isTrue,
      );
      final tokens = SessionTokens(_MemoryStore());
      final api = ApiClient(
        config: ApiConfig(),
        accessTokenProvider: () => tokens.accessToken,
      );
      final auth = AuthRepository(apiClient: api, tokens: tokens);
      api.tokenRefresher = auth.refreshSession;
      final session = SessionController(
        authRepository: auth,
        onboardingRepository: OnboardingRepository(api),
      );
      addTearDown(api.close);
      await tester.pumpWidget(NxtRepApp(sessionController: session));
      await _waitFor(tester, find.text('欢迎回来'));
      await tester.enterText(find.byType(TextFormField).first, username);
      await tester.enterText(find.byType(TextFormField).last, password);
      await tester.tap(find.text('登录'));
      await _waitFor(tester, find.byType(NavigationBar));

      for (final name in ['验收备用设备 A', '验收备用设备 B']) {
        await api.post(
          '/auth/login',
          authenticated: false,
          body: {
            'username': username,
            'password': password,
            'device_name': name,
          },
        );
      }
      await tester.tap(find.text('我的').last);
      await _waitFor(tester, find.text('账户安全'));
      await tester.ensureVisible(find.text('账户安全'));
      await tester.tap(find.text('账户安全'));
      await _waitFor(tester, find.text('当前设备'));
      expect(find.text('验收备用设备 A'), findsOneWidget);
      final devices = await auth.listSessions();
      final other = devices.singleWhere((row) => row.deviceName == '验收备用设备 A');
      final revoke = find.byKey(ValueKey('revoke-${other.id}'));
      await tester.ensureVisible(revoke);
      await tester.tap(revoke);
      await _waitFor(tester, find.text('确认退出'));
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();
      expect((await auth.listSessions()).length, 3);
      await tester.tap(revoke);
      await _waitFor(tester, find.text('确认退出'));
      await tester.tap(find.text('确认退出'));
      await _waitUntil(
        tester,
        () => !tester
            .widget<AccountSecurityPage>(find.byType(AccountSecurityPage))
            .controller
            .busy,
      );
      expect((await auth.listSessions()).length, 2);
      await tester.ensureVisible(find.text('退出其他所有设备'));
      await tester.tap(find.text('退出其他所有设备'));
      await _waitFor(tester, find.text('确认退出'));
      await tester.tap(find.text('确认退出'));
      await _waitFor(tester, find.text('目前只有当前设备保持登录。'));

      await tester.ensureVisible(find.text('修改密码'));
      await tester.tap(find.text('修改密码'));
      await _waitFor(tester, find.text('确认修改密码'));
      Future<void> fill(String key, String value) async {
        final field = find.byKey(ValueKey('password-$key'));
        await tester.ensureVisible(field);
        await tester.enterText(field, value);
      }

      Future<void> submit() async {
        await tester.ensureVisible(find.text('确认修改密码'));
        await tester.tap(find.text('确认修改密码'));
      }

      await fill('current', 'deliberately-wrong-password');
      await fill('next', nextPassword);
      await fill('repeat', nextPassword);
      await submit();
      await _waitFor(tester, find.text('当前密码不正确，请重新输入'));
      expect(session.phase, SessionPhase.authenticated);
      await fill('current', password);
      await submit();
      await _waitUntil(
        tester,
        () => find.byType(ChangePasswordPage).evaluate().isEmpty,
      );
      expect(session.phase, SessionPhase.authenticated);
      expect((await auth.listSessions()).length, 1);

      // A second authenticated client revokes this login while a protected page is open.
      final remotePair = await api.post(
        '/auth/login',
        authenticated: false,
        body: {
          'username': username,
          'password': nextPassword,
          'device_name': '验收远程退出',
        },
      ) as Map;
      final remote = ApiClient(
        config: ApiConfig(),
        accessTokenProvider: () => remotePair['access_token'] as String,
      );
      addTearDown(remote.close);
      final currentId = (await auth.listSessions())
          .singleWhere((row) => row.isCurrent)
          .id;
      await tester.ensureVisible(find.text('修改密码'));
      await tester.tap(find.text('修改密码'));
      await _waitFor(tester, find.byType(ChangePasswordPage));
      await remote.delete('/auth/sessions/$currentId');
      await expectLater(
        api.get('/auth/sessions'),
        throwsA(isA<ApiException>()),
      );
      await _waitFor(tester, find.text('欢迎回来'));
      expect(find.byType(AccountSecurityPage), findsNothing);
      expect(find.byType(ChangePasswordPage), findsNothing);
      expect(session.phase, SessionPhase.signedOut);
      expect(tokens.accessToken, isNull);
    },
  );
}

Future<void> _waitFor(WidgetTester tester, Finder finder) =>
    _waitUntil(tester, () => finder.evaluate().isNotEmpty);

Future<void> _waitUntil(WidgetTester tester, bool Function() done) async {
  for (var i = 0; i < 120; i++) {
    await tester.pump(const Duration(milliseconds: 250));
    if (done()) {
      await tester.pump(const Duration(milliseconds: 400));
      return;
    }
  }
  fail('Account security operation did not settle within 30 seconds');
}

class _MemoryStore implements RefreshTokenStore {
  String? value;
  @override
  Future<String?> read() async => value;
  @override
  Future<void> write(String token) async => value = token;
  @override
  Future<void> delete() async => value = null;
}

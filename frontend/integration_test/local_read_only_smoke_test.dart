import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nxtrep/app/nxtrep_app.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';

const _username = String.fromEnvironment('E2E_USERNAME');
const _password = String.fromEnvironment('E2E_PASSWORD');

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('local backend: login, plans, food and exercises load', (
    tester,
  ) async {
    expect(
      _username.isNotEmpty && _password.isNotEmpty,
      isTrue,
      reason: 'Pass E2E_USERNAME and E2E_PASSWORD with --dart-define.',
    );

    final tokens = SessionTokens(_MemoryRefreshTokenStore());
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
    await tester.enterText(find.byType(TextFormField).at(0), _username);
    await tester.enterText(find.byType(TextFormField).at(1), _password);
    await tester.tap(find.text('登录'));
    await _waitFor(tester, find.byType(NavigationBar));

    await tester.tap(find.text('计划').last);
    await _waitFor(tester, find.text('训练计划'));
    await _waitFor(tester, find.text('查看完整计划'));
    await tester.tap(find.text('查看完整计划'));
    await _waitFor(tester, find.text('当前训练计划'));
    expect(find.textContaining('第 1 天 ·'), findsOneWidget);
    expect(find.textContaining('组 ×'), findsWidgets);
    await tester.pageBack();
    await tester.pump(const Duration(milliseconds: 500));

    final browsePlans = find.textContaining(
      RegExp(r'^(?:浏览全部|全部) [1-9]\d* 套(?:计划)?$'),
    );
    await _waitFor(tester, browsePlans);
    await tester.ensureVisible(browsePlans);
    await tester.tap(browsePlans);
    await _waitFor(tester, find.text('全部训练计划'));
    expect(find.text('训练目标'), findsOneWidget);
    await tester.pageBack();
    await tester.pump(const Duration(milliseconds: 500));

    final exerciseLibrary = find.text('动作库');
    await tester.scrollUntilVisible(exerciseLibrary, 300);
    await tester.tap(exerciseLibrary);
    await _waitFor(tester, find.text('动作库'));
    await _waitFor(tester, find.textContaining('个动作'));
    await tester.pageBack();
    await tester.pump(const Duration(milliseconds: 500));

    await _waitFor(tester, find.text('首页'));
    await tester.tap(find.text('首页').last);
    await _waitFor(tester, find.text('食品与饮食'));
    await tester.tap(find.text('食品与饮食'));
    await _waitFor(tester, find.text('浏览食品库'));
    await tester.tap(find.text('浏览食品库'));
    await _waitFor(tester, find.text('食品库'));
    await _waitFor(tester, find.textContaining('常用食品 ·'));
  });
}

Future<void> _waitFor(WidgetTester tester, Finder finder) async {
  for (var attempt = 0; attempt < 40; attempt++) {
    await tester.pump(const Duration(milliseconds: 500));
    if (finder.evaluate().isNotEmpty) return;
  }
  expect(finder, findsWidgets);
}

class _MemoryRefreshTokenStore implements RefreshTokenStore {
  String? _token;

  @override
  Future<String?> read() async => _token;

  @override
  Future<void> write(String token) async {
    _token = token;
  }

  @override
  Future<void> delete() async {
    _token = null;
  }
}

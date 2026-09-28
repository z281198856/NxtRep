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

  testWidgets('local backend: AI plan explains metrics and previews draft', (
    tester,
  ) async {
    expect(_username.isNotEmpty && _password.isNotEmpty, isTrue);

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

    await tester.tap(find.text('AI教练').last);
    await _waitFor(tester, find.byTooltip('发送'));
    await tester.enterText(
      find.byType(TextField).last,
      '请为我生成一份每周3天的哑铃减脂保肌训练计划草稿，并结合我的身高体重体脂解释为什么适合我。',
    );
    await tester.tap(find.byTooltip('发送'));
    await _waitFor(tester, find.text('查看各训练日和动作'), attempts: 120);

    expect(find.text('回答'), findsOneWidget);
    expect(find.text('分析'), findsOneWidget);
    expect(find.textContaining('173 cm'), findsWidgets);
    expect(find.textContaining('70 kg'), findsWidgets);
    expect(find.textContaining('18%'), findsWidgets);

    await tester.ensureVisible(find.text('查看各训练日和动作'));
    await tester.drag(find.byType(ListView).last, const Offset(0, -320));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.tap(find.text('查看各训练日和动作'));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.textContaining('第 1 天 ·'), findsWidgets);
  });
}

Future<void> _waitFor(
  WidgetTester tester,
  Finder finder, {
  int attempts = 40,
}) async {
  for (var attempt = 0; attempt < attempts; attempt++) {
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

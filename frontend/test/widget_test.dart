import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:nxtrep/app/nxtrep_app.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
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

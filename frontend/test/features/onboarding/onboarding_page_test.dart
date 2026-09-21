import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/storage/refresh_token_store.dart';
import 'package:nxtrep/features/auth/data/auth_repository.dart';
import 'package:nxtrep/features/auth/domain/session_tokens.dart';
import 'package:nxtrep/features/auth/presentation/session_controller.dart';
import 'package:nxtrep/features/onboarding/data/onboarding_repository.dart';
import 'package:nxtrep/features/onboarding/presentation/onboarding_page.dart';

class _UnusedRefreshTokenStore implements RefreshTokenStore {
  @override
  Future<void> delete() async {}

  @override
  Future<String?> read() async => null;

  @override
  Future<void> write(String token) async {}
}

void main() {
  testWidgets('shows exactly the two supported first-run training modes', (
    tester,
  ) async {
    final tokens = SessionTokens(_UnusedRefreshTokenStore());
    final client = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => tokens.accessToken,
      httpClient: MockClient((_) async => http.Response('{}', 200)),
    );
    addTearDown(client.close);
    final controller = SessionController(
      authRepository: AuthRepository(apiClient: client, tokens: tokens),
      onboardingRepository: OnboardingRepository(client),
    );

    await tester.pumpWidget(
      MaterialApp(home: OnboardingPage(controller: controller)),
    );

    await tester.tap(find.widgetWithText(FilledButton, '继续'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '继续'));
    await tester.pumpAndSettle();

    expect(find.text('徒手训练'), findsOneWidget);
    expect(find.text('健身房器械训练'), findsOneWidget);
    expect(find.byIcon(Icons.check_circle_rounded), findsOneWidget);
    expect(find.byIcon(Icons.circle_outlined), findsOneWidget);
    expect(find.text('徒手'), findsNothing);
    expect(find.text('哑铃'), findsNothing);
    expect(find.text('杠铃'), findsNothing);
    expect(find.text('绳索器械'), findsNothing);
    expect(find.text('深蹲架'), findsNothing);
  });
}

import 'package:flutter/material.dart';

import 'app/nxtrep_app.dart';
import 'core/config/api_config.dart';
import 'core/network/api_client.dart';
import 'core/storage/refresh_token_store.dart';
import 'features/auth/data/auth_repository.dart';
import 'features/auth/domain/session_tokens.dart';
import 'features/auth/presentation/session_controller.dart';
import 'features/onboarding/data/onboarding_repository.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  final tokens = SessionTokens(SecureRefreshTokenStore());
  final apiClient = ApiClient(
    config: ApiConfig(),
    accessTokenProvider: () => tokens.accessToken,
  );
  final authRepository = AuthRepository(apiClient: apiClient, tokens: tokens);
  apiClient.tokenRefresher = authRepository.refreshSession;

  final sessionController = SessionController(
    authRepository: authRepository,
    onboardingRepository: OnboardingRepository(apiClient),
  );

  runApp(
    NxtRepApp(sessionController: sessionController, onDispose: apiClient.close),
  );
}

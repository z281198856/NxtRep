import 'package:flutter/material.dart';

import '../../onboarding/presentation/onboarding_page.dart';
import '../../shell/presentation/home_shell.dart';
import 'app_loading_page.dart';
import 'login_page.dart';
import 'password_setup_page.dart';
import 'session_controller.dart';

class AuthGate extends StatelessWidget {
  const AuthGate({super.key, required this.controller});

  final SessionController controller;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) => switch (controller.phase) {
        SessionPhase.loading => const AppLoadingPage(),
        SessionPhase.signedOut => LoginPage(controller: controller),
        SessionPhase.passwordSetupRequired => PasswordSetupPage(
          controller: controller,
          initialUsername: controller.setupUsername,
        ),
        SessionPhase.onboardingRequired => OnboardingPage(
          controller: controller,
        ),
        SessionPhase.authenticated => HomeShell(controller: controller),
      },
    );
  }
}

import 'package:flutter/foundation.dart';

import '../../../core/network/api_exception.dart';
import '../../onboarding/data/onboarding_repository.dart';
import '../../onboarding/domain/onboarding_models.dart';
import '../data/auth_repository.dart';
import '../domain/auth_models.dart';

enum SessionPhase {
  loading,
  signedOut,
  passwordSetupRequired,
  onboardingRequired,
  authenticated,
}

class SessionController extends ChangeNotifier {
  SessionController({
    required this.authRepository,
    required this.onboardingRepository,
  });

  final AuthRepository authRepository;
  final OnboardingRepository onboardingRepository;

  SessionPhase phase = SessionPhase.loading;
  CurrentAccount? account;
  bool submitting = false;
  String? errorMessage;
  String? setupUsername;
  bool _initialized = false;

  Future<void> initialize() async {
    if (_initialized) return;
    _initialized = true;

    try {
      final refreshed = await authRepository.refreshSession();
      if (!refreshed) {
        phase = SessionPhase.signedOut;
      } else {
        await _loadAccount();
      }
    } on ApiException catch (error) {
      phase = SessionPhase.signedOut;
      errorMessage = _messageFor(error);
    } finally {
      notifyListeners();
    }
  }

  Future<void> login(String username, String password) async {
    await _perform(() async {
      try {
        await authRepository.login(
          username: username.trim(),
          password: password,
          deviceName: 'NxtRep Flutter',
        );
        await _loadAccount();
      } on ApiException catch (error) {
        if (error.code == 'PASSWORD_SETUP_REQUIRED') {
          setupUsername = username.trim();
          phase = SessionPhase.passwordSetupRequired;
          return;
        }
        rethrow;
      }
    });
  }

  Future<void> setupPassword({
    required String username,
    required String setupToken,
    required String newPassword,
  }) async {
    await _perform(() async {
      await authRepository.setupPassword(
        username: username.trim(),
        setupToken: setupToken.trim(),
        newPassword: newPassword,
      );
      await _loadAccount();
    });
  }

  Future<void> completeOnboarding(OnboardingSubmission submission) async {
    await _perform(() async {
      await onboardingRepository.complete(submission);
      await _loadAccount();
      if (phase == SessionPhase.onboardingRequired) {
        throw const ApiException(
          code: 'PROFILE_INITIALIZATION_INCOMPLETE',
          message: '资料已保存，但后端仍报告初始化未完成',
        );
      }
    });
  }

  Future<void> logout() async {
    await _perform(() async {
      await authRepository.logout();
      account = null;
      phase = SessionPhase.signedOut;
    });
  }

  void showLogin() {
    errorMessage = null;
    phase = SessionPhase.signedOut;
    notifyListeners();
  }

  Future<void> _loadAccount() async {
    final current = await authRepository.getCurrentAccount();
    account = current;
    setupUsername = current.username;
    if (current.passwordSetupRequired) {
      phase = SessionPhase.passwordSetupRequired;
    } else if (!current.profileInitialized) {
      phase = SessionPhase.onboardingRequired;
    } else {
      phase = SessionPhase.authenticated;
    }
  }

  Future<void> _perform(Future<void> Function() action) async {
    if (submitting) return;
    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      await action();
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      if (error.isAuthenticationFailure) {
        await authRepository.clearLocalSession();
        account = null;
        phase = SessionPhase.signedOut;
      }
    } on Object {
      errorMessage = '发生了未预期的错误，请稍后重试';
    } finally {
      submitting = false;
      notifyListeners();
    }
  }

  String _messageFor(ApiException error) => switch (error.code) {
    'INVALID_CREDENTIALS' => '用户名或密码不正确',
    'ACCOUNT_LOCKED' => '账户已锁定，请稍后再试',
    'ACCOUNT_DISABLED' => '账户已停用',
    'INVALID_SETUP_TOKEN' => '设置令牌无效或已过期',
    'VALIDATION_ERROR' => '填写内容不符合要求，请检查后重试',
    'PROFILE_VERSION_CONFLICT' ||
    'GOALS_VERSION_CONFLICT' => '资料已在其他位置更新，请重新提交',
    'NETWORK_ERROR' => '连接不到后端，请确认服务已启动',
    _ => error.message,
  };
}

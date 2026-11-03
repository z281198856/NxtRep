import 'dart:async';

import '../../../core/network/api_exception.dart';
import '../../../core/notifications/reminder_controller.dart';
import '../../../core/offline/local_records.dart';
import '../../../core/state/lifecycle_notifier.dart';
import '../../onboarding/data/onboarding_repository.dart';
import '../../onboarding/domain/onboarding_models.dart';
import '../../profile/data/profile_repository.dart';
import '../../profile/domain/profile_models.dart';
import '../data/auth_repository.dart';
import '../domain/auth_models.dart';

enum SessionPhase {
  loading,
  signedOut,
  passwordSetupRequired,
  onboardingRequired,
  authenticated,
}

class SessionController extends LifecycleNotifier {
  SessionController({
    required this.authRepository,
    required this.onboardingRepository,
    this.systemReminders,
  }) {
    authRepository.apiClient.onAuthenticationExpired = _authenticationExpired;
  }

  final AuthRepository authRepository;
  final OnboardingRepository onboardingRepository;
  final LocalReminderController? systemReminders;

  SessionPhase phase = SessionPhase.loading;
  CurrentAccount? account;
  AppSettings? appSettings;
  bool submitting = false;
  String? errorMessage;
  String? setupUsername;
  bool _initialized = false;
  bool _reconnecting = false;
  bool offline = false;
  LocalRecords? get localRecords => authRepository.apiClient.localRecords;

  Future<void> initialize() async {
    if (_initialized) return;
    _initialized = true;

    try {
      final refreshed = await authRepository.refreshSession();
      if (!refreshed) {
        phase = SessionPhase.signedOut;
        await localRecords?.unbind();
      } else {
        await _loadAccount();
      }
    } on ApiException catch (error) {
      if (!LocalRecords.transient(error) || !await _restoreOfflineAccount()) {
        phase = SessionPhase.signedOut;
        errorMessage = _messageFor(error);
      }
    } on Object {
      phase = SessionPhase.signedOut;
      errorMessage = '本机登录状态暂不可用，请重新登录；草稿和记录不会删除';
    } finally {
      if (phase != SessionPhase.authenticated) {
        await systemReminders?.deactivate();
      }
      notifyListeners();
    }
  }

  Future<void> login(String username, String password) async {
    await _perform(() async {
      await localRecords?.unbind();
      try {
        await authRepository.login(
          username: username.trim(),
          password: password,
          deviceName: AuthRepository.deviceName,
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
      try {
        await authRepository.logout();
      } finally {
        offline = false;
        account = null;
        appSettings = null;
        phase = SessionPhase.signedOut;
        await systemReminders?.deactivate();
        await localRecords?.unbind();
      }
    });
  }

  void _authenticationExpired() {
    if (isDisposed || phase == SessionPhase.signedOut) return;
    unawaited(requireLogin('登录已失效，请重新登录'));
  }

  Future<void> requireLogin(String message) async {
    if (isDisposed) return;
    account = null;
    appSettings = null;
    phase = SessionPhase.signedOut;
    errorMessage = message;
    notifyListeners();
    await systemReminders?.deactivate();
    try {
      await localRecords?.unbind();
    } on Object {
      /* Hide local data even if pointer removal fails. */
    }
    offline = false;
    try {
      await authRepository.clearLocalSession();
    } on Object {
      // SessionTokens clears memory before deleting its platform storage.
    }
  }

  @override
  void dispose() {
    if (authRepository.apiClient.onAuthenticationExpired ==
        _authenticationExpired) {
      authRepository.apiClient.onAuthenticationExpired = null;
    }
    super.dispose();
  }

  void showLogin() {
    errorMessage = null;
    appSettings = null;
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
      offline = false;
      localRecords?.localOnly = false;
      final local = localRecords;
      if (local != null) {
        try {
          await local.bind(
            authRepository.apiClient.config.resolve('/').toString(),
            current.id,
          );
          await local.saveBootstrap({
            'server': authRepository.apiClient.config.resolve('/').toString(),
            'account': {
              'id': current.id,
              'username': current.username,
              'status': current.status,
              'is_admin': current.isAdmin,
              'password_setup_required': current.passwordSetupRequired,
              'profile_initialized': current.profileInitialized,
            },
          });
        } on Object {
          errorMessage = '本地记录存储暂不可用，请保留输入并重试';
          local.reportStorageError('本机记录暂时无法读取，旧内容已保留，请稍后重试');
        }
      }
      // A settings outage must not prevent login. The profile page can retry.
      appSettings = null;
      try {
        appSettings = await ProfileRepository(authRepository.apiClient)
            .getSettings();
      } on Object {
        appSettings = null;
      }
      if (phase == SessionPhase.authenticated && account?.id == current.id) {
        await systemReminders?.activate(
          authRepository.apiClient.config.resolve('/').toString(),
          current.id,
        );
      }
    }
  }

  Future<bool> _restoreOfflineAccount() async {
    final local = localRecords;
    if (local == null) return false;
    try {
      if (await authRepository.tokens.loadRefreshToken() == null) return false;
      final snapshot = await local.bootstrap();
      final server = authRepository.apiClient.config.resolve('/').toString();
      if (snapshot == null || snapshot['server'] != server) return false;
      final current = CurrentAccount.fromJson(
        Map<String, dynamic>.from(snapshot['account'] as Map),
      );
      if (!current.profileInitialized ||
          current.passwordSetupRequired ||
          current.status != 'active') {
        return false;
      }
      await local.bind(server, current.id);
      local.localOnly = true;
      local.usingCache = true;
      account = current;
      offline = true;
      phase = SessionPhase.authenticated;
      // Preserve the last unit setting for interpreting restored form inputs.
      try {
        appSettings = await ProfileRepository(authRepository.apiClient)
            .getSettings();
      } on Object {
        /* No cached settings yet. */
      }
      await systemReminders?.activate(server, current.id);
      return true;
    } on Object {
      return false;
    }
  }

  Future<void> reconnectAndSync() async {
    if (_reconnecting || phase != SessionPhase.authenticated || isDisposed) {
      return;
    }
    _reconnecting = true;
    try {
      if (offline) {
        if (!await authRepository.refreshSession()) {
          await requireLogin('登录已失效，请重新登录；本机记录会在同一账户登录后恢复');
          return;
        }
        localRecords?.localOnly = false;
        await _loadAccount();
        notifyListeners();
      }
      if (!offline && localRecords?.usingCache == true) {
        await authRepository.getCurrentAccount();
        localRecords?.usingCache = false;
        localRecords?.syncRevision++;
      }
      await authRepository.apiClient.syncLocalRecords();
    } on ApiException catch (e) {
      if (e.isAuthenticationFailure) await requireLogin('登录已失效，请重新登录');
    } on Object {
      // The journal retains every unacknowledged record; the status page retries.
    } finally {
      _reconnecting = false;
    }
  }

  void applySettings(AppSettings settings) {
    if (phase != SessionPhase.authenticated) return;
    appSettings = settings;
    notifyListeners();
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
        appSettings = null;
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

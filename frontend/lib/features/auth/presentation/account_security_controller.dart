import '../../../core/network/api_exception.dart';
import '../../../core/state/lifecycle_notifier.dart';
import '../data/auth_repository.dart';
import '../domain/auth_models.dart';

class AccountSecurityController extends LifecycleNotifier {
  AccountSecurityController(this.repository, {required this.onRequireLogin});

  final AuthRepository repository;
  final Future<void> Function(String message) onRequireLogin;
  List<AccountSession> sessions = const [];
  bool loading = false;
  bool managing = false;
  bool changingPassword = false;
  String? errorMessage;
  String? errorCode;
  bool get busy => loading || managing || changingPassword;
  int get otherCount => sessions.where((session) => !session.isCurrent).length;

  void clearError() {
    errorMessage = null;
    errorCode = null;
    notifyListeners();
  }

  Future<void> refresh() async {
    if (busy || isDisposed) return;
    loading = true;
    clearError();
    try {
      sessions = await repository.listSessions();
    } on ApiException catch (error) {
      errorMessage = _message(error);
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<bool> revoke(AccountSession? session) async {
    if (busy || isDisposed || session?.isCurrent == true) return false;
    managing = true;
    clearError();
    try {
      if (session == null) {
        await repository.revokeOtherSessions();
        sessions = sessions.where((row) => row.isCurrent).toList();
      } else {
        await repository.revokeSession(session.id);
        sessions = sessions.where((row) => row.id != session.id).toList();
      }
      try {
        sessions = await repository.listSessions();
      } on ApiException {
        errorMessage = '设备已退出，但列表暂时无法刷新，请下拉重试';
      }
      return true;
    } on ApiException catch (error) {
      errorCode = error.code;
      errorMessage = _uncertain(error)
          ? '退出操作结果暂时无法确认，请刷新设备列表核对后再试'
          : _message(error);
      return false;
    } finally {
      managing = false;
      notifyListeners();
    }
  }

  Future<bool> changePassword(String current, String next) async {
    if (busy || isDisposed) return false;
    changingPassword = true;
    clearError();
    try {
      await repository.changePassword(
        currentPassword: current,
        newPassword: next,
      );
      try {
        sessions = await repository.listSessions();
      } on ApiException {
        errorMessage = '密码已修改，登录设备列表暂时无法刷新';
      }
      return true;
    } on ApiException catch (error) {
      errorCode = error.code;
      errorMessage = _message(error);
      if (_uncertain(error) ||
          error.code == 'SESSION_SAVE_FAILED' ||
          error.isAuthenticationFailure) {
        final message = error.code == 'SESSION_SAVE_FAILED'
            ? '密码已修改，请使用新密码重新登录'
            : error.isAuthenticationFailure
            ? '登录已失效，请重新登录'
            : '密码修改结果暂时无法确认，请重新登录核对。若新密码不可用，请尝试原密码。';
        await onRequireLogin(message);
      }
      return false;
    } finally {
      changingPassword = false;
      notifyListeners();
    }
  }

  bool _uncertain(ApiException error) =>
      {
        'REQUEST_TIMEOUT',
        'NETWORK_ERROR',
        'INVALID_SUCCESS_RESPONSE',
      }.contains(error.code) ||
      (error.statusCode ?? 0) >= 500;

  String _message(ApiException error) => switch (error.code) {
    'INVALID_CURRENT_PASSWORD' => '当前密码不正确，请重新输入',
    'PASSWORD_REUSE_NOT_ALLOWED' => '新密码不能与当前密码相同',
    'ACCOUNT_LOCKED' => '尝试次数过多，请 15 分钟后再试',
    'REFRESH_SESSION_NOT_FOUND' => '这条登录记录已退出或不存在，请刷新列表',
    'VALIDATION_ERROR' => '请检查填写内容，密码长度应为 8–128 个字符',
    'INVALID_ACCESS_TOKEN' ||
    'AUTHENTICATION_REQUIRED' ||
    'INVALID_REFRESH_TOKEN' => '登录已失效，请重新登录',
    'ACCOUNT_DISABLED' => '账号已停用',
    'NETWORK_ERROR' => '暂时无法连接，请检查网络后重试',
    _ => error.message,
  };
}

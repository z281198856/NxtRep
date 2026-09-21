import '../../../core/network/api_client.dart';
import '../../../core/network/api_exception.dart';
import '../domain/auth_models.dart';
import '../domain/session_tokens.dart';

class AuthRepository {
  AuthRepository({required this.apiClient, required this.tokens});

  final ApiClient apiClient;
  final SessionTokens tokens;

  Future<TokenPair> login({
    required String username,
    required String password,
    String? deviceName,
  }) async {
    final body = <String, Object>{'username': username, 'password': password};
    if (deviceName != null) {
      body['device_name'] = deviceName;
    }
    final json = expectJsonObject(
      await apiClient.post('/auth/login', authenticated: false, body: body),
      context: '登录接口',
    );
    final pair = TokenPair.fromJson(json);
    await tokens.replace(pair);
    return pair;
  }

  Future<TokenPair> setupPassword({
    required String username,
    required String setupToken,
    required String newPassword,
  }) async {
    final json = expectJsonObject(
      await apiClient.post(
        '/auth/password/setup',
        authenticated: false,
        body: {
          'username': username,
          'setup_token': setupToken,
          'new_password': newPassword,
        },
      ),
      context: '密码设置接口',
    );
    final pair = TokenPair.fromJson(json);
    await tokens.replace(pair);
    return pair;
  }

  Future<bool> refreshSession() async {
    final refreshToken = await tokens.loadRefreshToken();
    if (refreshToken == null) {
      return false;
    }

    try {
      final json = expectJsonObject(
        await apiClient.post(
          '/auth/refresh',
          authenticated: false,
          body: {'refresh_token': refreshToken},
        ),
        context: '令牌刷新接口',
      );
      await tokens.replace(TokenPair.fromJson(json));
      return true;
    } on ApiException catch (error) {
      if (error.statusCode == 401 || error.statusCode == 403) {
        await tokens.clear();
        return false;
      }
      rethrow;
    }
  }

  Future<CurrentAccount> getCurrentAccount() async {
    final json = expectJsonObject(await apiClient.get('/me'), context: '账户接口');
    return CurrentAccount.fromJson(json);
  }

  Future<void> logout() async {
    final refreshToken = tokens.refreshToken ?? await tokens.loadRefreshToken();
    try {
      if (refreshToken != null) {
        await apiClient.post(
          '/auth/logout',
          authenticated: false,
          body: {'refresh_token': refreshToken},
        );
      }
    } finally {
      await tokens.clear();
    }
  }

  Future<void> clearLocalSession() => tokens.clear();
}

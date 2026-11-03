import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/api_exception.dart';
import '../domain/auth_models.dart';
import '../domain/session_tokens.dart';

class AuthRepository {
  AuthRepository({required this.apiClient, required this.tokens});

  final ApiClient apiClient;
  final SessionTokens tokens;
  Future<void> _tokenTail = Future.value();

  static String get deviceName => switch (defaultTargetPlatform) {
    TargetPlatform.android => 'Android 设备',
    TargetPlatform.iOS => 'iPhone / iPad',
    TargetPlatform.windows => 'Windows 设备',
    TargetPlatform.macOS => 'Mac 设备',
    _ => 'NxtRep 设备',
  };

  Future<T> _withTokenLock<T>(Future<T> Function() action) async {
    final previous = _tokenTail;
    final release = Completer<void>();
    _tokenTail = release.future;
    await previous;
    try {
      return await action();
    } finally {
      release.complete();
    }
  }

  Future<TokenPair> login({
    required String username,
    required String password,
    String? deviceName,
  }) => _withTokenLock(() async {
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
  });

  Future<TokenPair> setupPassword({
    required String username,
    required String setupToken,
    required String newPassword,
  }) => _withTokenLock(() async {
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
  });

  Future<bool> refreshSession() => _withTokenLock(() async {
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
    } on Object {
      try {
        await tokens.clear();
      } on Object {
        /* Memory is already cleared. */
      }
      apiClient.onAuthenticationExpired?.call();
      throw const ApiException(
        code: 'SESSION_SAVE_FAILED',
        message: '登录状态无法安全保存，请重新登录',
      );
    }
  });

  Future<CurrentAccount> getCurrentAccount() async {
    final json = expectJsonObject(await apiClient.get('/me'), context: '账户接口');
    return CurrentAccount.fromJson(json);
  }

  Future<void> logout() => _withTokenLock(() async {
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
  });

  Future<void> clearLocalSession() => _withTokenLock(tokens.clear);

  Future<TokenPair> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    for (var attempt = 0; attempt < 2; attempt++) {
      try {
        return await _withTokenLock(() async {
          // Do not refresh while holding the token lock. Retry only a rejected
          // access token, which guarantees the password operation did not run.
          final json = expectJsonObject(
            await apiClient.request(
              'POST',
              '/auth/password/change',
              refreshAuthentication: false,
              body: {
                'current_password': currentPassword,
                'new_password': newPassword,
                'device_name': deviceName,
              },
            ),
            context: '修改密码接口',
          );
          final pair = TokenPair.fromJson(json);
          try {
            await tokens.replace(pair);
          } on Object {
            throw const ApiException(
              code: 'SESSION_SAVE_FAILED',
              message: '密码已修改，但登录状态保存失败，请使用新密码重新登录',
            );
          }
          return pair;
        });
      } on ApiException catch (error) {
        if (attempt == 0 &&
            {
              'INVALID_ACCESS_TOKEN',
              'AUTHENTICATION_REQUIRED',
            }.contains(error.code) &&
            await refreshSession()) {
          continue;
        }
        rethrow;
      } on Object {
        throw const ApiException(
          code: 'INVALID_SUCCESS_RESPONSE',
          message: '修改结果暂时无法确认，请重新登录后核对',
        );
      }
    }
    throw StateError('Unreachable password retry');
  }

  Future<List<AccountSession>> listSessions() async {
    final json = expectJsonObject(
      await apiClient.get('/auth/sessions'),
      context: '登录设备接口',
    );
    try {
      final sessions = (json['sessions'] as List)
          .map(
            (row) =>
                AccountSession.fromJson(Map<String, dynamic>.from(row as Map)),
          )
          .toList();
      if (sessions.where((row) => row.isCurrent).length != 1) {
        throw const FormatException();
      }
      return sessions;
    } on Object {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '登录设备状态不完整，请刷新重试',
      );
    }
  }

  Future<void> revokeSession(String id) async {
    await apiClient.delete('/auth/sessions/${Uri.encodeComponent(id)}');
  }

  Future<void> revokeOtherSessions() async {
    await apiClient.post('/auth/sessions/revoke-others');
  }
}

import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  const ApiException({
    required this.code,
    required this.message,
    this.statusCode,
    this.details,
  });

  factory ApiException.fromResponse(http.Response response) {
    try {
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      if (decoded is Map<String, dynamic>) {
        final error = decoded['error'];
        if (error is Map<String, dynamic>) {
          return ApiException(
            statusCode: response.statusCode,
            code: error['code'] as String? ?? 'HTTP_ERROR',
            message: error['message'] as String? ?? '请求失败',
            details: error['details'],
          );
        }
      }
    } on FormatException {
      // Fall through to a protocol-safe error below.
    }

    return ApiException(
      statusCode: response.statusCode,
      code: 'INVALID_ERROR_RESPONSE',
      message: '服务器返回了无法识别的错误响应',
    );
  }

  factory ApiException.network(Object cause) => ApiException(
    code: 'NETWORK_ERROR',
    message: '无法连接服务器，请检查网络和后端服务',
    details: cause,
  );

  final int? statusCode;
  final String code;
  final String message;
  final Object? details;

  bool get isAuthenticationFailure =>
      code == 'AUTHENTICATION_REQUIRED' ||
      code == 'INVALID_REFRESH_TOKEN' ||
      code == 'REFRESH_TOKEN_REUSED' ||
      code == 'REFRESH_TOKEN_EXPIRED' ||
      code == 'ACCOUNT_DISABLED';

  @override
  String toString() => 'ApiException($code, $statusCode): $message';
}

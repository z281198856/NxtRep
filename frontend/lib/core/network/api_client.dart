import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../config/api_config.dart';
import 'api_exception.dart';
import 'sse_event.dart';

typedef AccessTokenProvider = String? Function();
typedef TokenRefresher = Future<bool> Function();

class ApiClient {
  ApiClient({
    required this.config,
    required this.accessTokenProvider,
    http.Client? httpClient,
  }) : _httpClient = httpClient ?? http.Client();

  final ApiConfig config;
  final AccessTokenProvider accessTokenProvider;
  final http.Client _httpClient;

  TokenRefresher? tokenRefresher;
  Future<bool>? _refreshInFlight;

  Future<Object?> get(
    String path, {
    bool authenticated = true,
    Map<String, String>? query,
  }) => request('GET', path, authenticated: authenticated, query: query);

  Future<Object?> post(
    String path, {
    Object? body,
    bool authenticated = true,
    String? idempotencyKey,
  }) => request(
    'POST',
    path,
    body: body,
    authenticated: authenticated,
    idempotencyKey: idempotencyKey,
  );

  Future<Object?> patch(
    String path, {
    Object? body,
    bool authenticated = true,
    String? idempotencyKey,
  }) => request(
    'PATCH',
    path,
    body: body,
    authenticated: authenticated,
    idempotencyKey: idempotencyKey,
  );

  Future<Object?> put(
    String path, {
    Object? body,
    bool authenticated = true,
    String? idempotencyKey,
  }) => request(
    'PUT',
    path,
    body: body,
    authenticated: authenticated,
    idempotencyKey: idempotencyKey,
  );

  Future<Object?> delete(
    String path, {
    Object? body,
    bool authenticated = true,
  }) => request('DELETE', path, body: body, authenticated: authenticated);

  Future<Object?> request(
    String method,
    String path, {
    Object? body,
    bool authenticated = true,
    Map<String, String>? query,
    String? idempotencyKey,
  }) async {
    var response = await _send(
      method,
      path,
      body: body,
      authenticated: authenticated,
      query: query,
      idempotencyKey: idempotencyKey,
    );

    if (authenticated && response.statusCode == HttpStatus.unauthorized) {
      final refreshed = await _coalescedRefresh();
      if (refreshed) {
        response = await _send(
          method,
          path,
          body: body,
          authenticated: true,
          query: query,
          idempotencyKey: idempotencyKey,
        );
      }
    }

    return _decode(response);
  }

  Stream<SseEvent> postSse(
    String path, {
    required Object body,
    Map<String, String>? query,
    String? idempotencyKey,
  }) async* {
    var retried = false;
    while (true) {
      final request = _buildRequest(
        'POST',
        path,
        body: body,
        authenticated: true,
        query: query,
        idempotencyKey: idempotencyKey,
        accept: 'text/event-stream',
      );

      late http.StreamedResponse response;
      try {
        response = await _httpClient.send(request);
      } on Object catch (error) {
        throw ApiException.network(error);
      }

      if (!retried && response.statusCode == HttpStatus.unauthorized) {
        await response.stream.drain<void>();
        retried = true;
        if (await _coalescedRefresh()) {
          continue;
        }
      }

      if (response.statusCode < 200 || response.statusCode >= 300) {
        final bytes = await response.stream.toBytes();
        throw ApiException.fromResponse(
          http.Response.bytes(
            bytes,
            response.statusCode,
            headers: response.headers,
            reasonPhrase: response.reasonPhrase,
            request: response.request,
          ),
        );
      }

      final contentType = response.headers['content-type'] ?? '';
      if (!contentType.contains('text/event-stream')) {
        await response.stream.drain<void>();
        throw const ApiException(
          code: 'INVALID_STREAM_RESPONSE',
          message: '服务器未返回事件流',
        );
      }

      final lines = response.stream
          .transform(utf8.decoder)
          .transform(const LineSplitter());
      yield* parseSseLines(lines);
      return;
    }
  }

  Future<http.Response> _send(
    String method,
    String path, {
    Object? body,
    required bool authenticated,
    Map<String, String>? query,
    String? idempotencyKey,
  }) async {
    try {
      final streamed = await _httpClient.send(
        _buildRequest(
          method,
          path,
          body: body,
          authenticated: authenticated,
          query: query,
          idempotencyKey: idempotencyKey,
        ),
      );
      return await http.Response.fromStream(streamed);
    } on ApiException {
      rethrow;
    } on Object catch (error) {
      throw ApiException.network(error);
    }
  }

  http.Request _buildRequest(
    String method,
    String path, {
    Object? body,
    required bool authenticated,
    Map<String, String>? query,
    String? idempotencyKey,
    String accept = 'application/json',
  }) {
    var uri = config.resolve(path);
    if (query != null && query.isNotEmpty) {
      uri = uri.replace(queryParameters: {...uri.queryParameters, ...query});
    }

    final request = http.Request(method, uri);
    request.headers['Accept'] = accept;
    if (body != null) {
      request.headers['Content-Type'] = 'application/json; charset=utf-8';
      request.body = jsonEncode(body);
    }
    if (idempotencyKey != null) {
      request.headers['Idempotency-Key'] = idempotencyKey;
    }
    if (authenticated) {
      final token = accessTokenProvider();
      if (token != null) {
        request.headers['Authorization'] = 'Bearer $token';
      }
    }
    return request;
  }

  Future<bool> _coalescedRefresh() {
    final existing = _refreshInFlight;
    if (existing != null) {
      return existing;
    }

    final refresher = tokenRefresher;
    if (refresher == null) {
      return Future.value(false);
    }

    final future = refresher();
    _refreshInFlight = future;
    return future.whenComplete(() {
      if (identical(_refreshInFlight, future)) {
        _refreshInFlight = null;
      }
    });
  }

  Object? _decode(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException.fromResponse(response);
    }
    if (response.statusCode == HttpStatus.noContent ||
        response.bodyBytes.isEmpty) {
      return null;
    }

    try {
      return jsonDecode(utf8.decode(response.bodyBytes));
    } on FormatException {
      throw ApiException(
        statusCode: response.statusCode,
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '服务器返回了无法识别的成功响应',
      );
    }
  }

  void close() => _httpClient.close();
}

Map<String, dynamic> expectJsonObject(
  Object? value, {
  required String context,
}) {
  if (value is Map<String, dynamic>) {
    return value;
  }
  throw ApiException(
    code: 'INVALID_SUCCESS_RESPONSE',
    message: '$context 返回格式不正确',
  );
}

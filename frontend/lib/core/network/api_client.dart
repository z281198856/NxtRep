import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

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
    Duration connectionTimeout = const Duration(seconds: 8),
    this.requestTimeout = const Duration(seconds: 15),
  }) : _httpClient = httpClient ?? _defaultHttpClient(connectionTimeout);

  final ApiConfig config;
  final AccessTokenProvider accessTokenProvider;
  final http.Client _httpClient;
  final Duration requestTimeout;

  TokenRefresher? tokenRefresher;
  Future<bool>? _refreshInFlight;

  static http.Client _defaultHttpClient(Duration connectionTimeout) {
    final client = HttpClient()..connectionTimeout = connectionTimeout;
    return IOClient(client);
  }

  Future<Object?> get(
    String path, {
    bool authenticated = true,
    Map<String, String>? query,
    Duration? timeout,
  }) => request(
    'GET',
    path,
    authenticated: authenticated,
    query: query,
    timeout: timeout,
  );

  Future<Object?> post(
    String path, {
    Object? body,
    bool authenticated = true,
    String? idempotencyKey,
    Duration? timeout,
  }) => request(
    'POST',
    path,
    body: body,
    authenticated: authenticated,
    idempotencyKey: idempotencyKey,
    timeout: timeout,
  );

  Future<Object?> patch(
    String path, {
    Object? body,
    bool authenticated = true,
    String? idempotencyKey,
    Duration? timeout,
  }) => request(
    'PATCH',
    path,
    body: body,
    authenticated: authenticated,
    idempotencyKey: idempotencyKey,
    timeout: timeout,
  );

  Future<Object?> put(
    String path, {
    Object? body,
    bool authenticated = true,
    String? idempotencyKey,
    Duration? timeout,
  }) => request(
    'PUT',
    path,
    body: body,
    authenticated: authenticated,
    idempotencyKey: idempotencyKey,
    timeout: timeout,
  );

  Future<Object?> delete(
    String path, {
    Object? body,
    bool authenticated = true,
    Duration? timeout,
  }) => request(
    'DELETE',
    path,
    body: body,
    authenticated: authenticated,
    timeout: timeout,
  );

  Future<Object?> request(
    String method,
    String path, {
    Object? body,
    bool authenticated = true,
    Map<String, String>? query,
    String? idempotencyKey,
    Duration? timeout,
  }) async {
    var response = await _send(
      method,
      path,
      body: body,
      authenticated: authenticated,
      query: query,
      idempotencyKey: idempotencyKey,
      timeout: timeout,
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
          timeout: timeout,
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
      final abort = Completer<void>();
      final request = _buildRequest(
        'POST',
        path,
        body: body,
        authenticated: true,
        query: query,
        idempotencyKey: idempotencyKey,
        accept: 'text/event-stream',
        abortTrigger: abort.future,
      );

      late http.StreamedResponse response;
      try {
        response = await _withTimeout(
          _httpClient.send(request),
          timeout: requestTimeout,
          abort: abort,
        );
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
    Duration? timeout,
  }) async {
    final abort = Completer<void>();
    try {
      final response = () async {
        final streamed = await _httpClient.send(
          _buildRequest(
            method,
            path,
            body: body,
            authenticated: authenticated,
            query: query,
            idempotencyKey: idempotencyKey,
            abortTrigger: abort.future,
          ),
        );
        return http.Response.fromStream(streamed);
      }();
      return await _withTimeout(
        response,
        timeout: timeout ?? requestTimeout,
        abort: abort,
      );
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
    Future<void>? abortTrigger,
  }) {
    var uri = config.resolve(path);
    if (query != null && query.isNotEmpty) {
      uri = uri.replace(queryParameters: {...uri.queryParameters, ...query});
    }

    final request = abortTrigger == null
        ? http.Request(method, uri)
        : http.AbortableRequest(method, uri, abortTrigger: abortTrigger);
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

  Future<T> _withTimeout<T>(
    Future<T> future, {
    required Duration timeout,
    required Completer<void> abort,
  }) => future.timeout(
    timeout,
    onTimeout: () {
      if (!abort.isCompleted) {
        abort.complete();
      }
      throw TimeoutException('API request timed out after $timeout');
    },
  );

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

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

import '../config/api_config.dart';
import '../offline/local_records.dart';
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
    this.streamProgressTimeout = const Duration(seconds: 150),
  }) : _httpClient = httpClient ?? _defaultHttpClient(connectionTimeout);

  final ApiConfig config;
  final AccessTokenProvider accessTokenProvider;
  final http.Client _httpClient;
  final Duration requestTimeout;
  final Duration streamProgressTimeout;

  TokenRefresher? tokenRefresher;
  void Function()? onAuthenticationExpired;
  LocalRecords? localRecords;
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
    String? localDraftKey,
    Duration? timeout,
  }) => request(
    'POST',
    path,
    body: body,
    authenticated: authenticated,
    idempotencyKey: idempotencyKey,
    localDraftKey: localDraftKey,
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
    String? localDraftKey,
    Duration? timeout,
    bool refreshAuthentication = true,
  }) async {
    final local = localRecords;
    if (authenticated &&
        local != null &&
        !local.bound &&
        LocalRecords.canRecord(method, path, idempotencyKey)) {
      throw const ApiException(
        code: 'LOCAL_STORAGE_FAILED',
        message: '本机记录存储尚未就绪，请保留当前内容，重新登录后重试',
      );
    }
    if (authenticated && local != null && local.bound) {
      if (LocalRecords.canRecord(method, path, idempotencyKey)) {
        return local.record(
          path,
          Map<String, dynamic>.from(body as Map),
          idempotencyKey!,
          _sendRecord,
          draftKey: localDraftKey,
        );
      }
      if (method != 'GET' &&
          (path.contains('/local-') ||
              (path.startsWith('/workouts/') &&
                  !path.endsWith('/sets') &&
                  local.hasWorkoutPending(path)))) {
        throw const ApiException(
          code: 'PENDING_WORKOUT_RECORDS',
          message: '这场训练还有待同步的组，请先到“离线记录与草稿”同步或处理，再修改或结束训练',
        );
      }
      if (method == 'GET' && LocalRecords.canCache(path)) {
        try {
          final result = await _onlineRequest(
            method,
            path,
            body: body,
            authenticated: authenticated,
            query: query,
            idempotencyKey: idempotencyKey,
            timeout: timeout,
            refreshAuthentication: refreshAuthentication,
          );
          try {
            await local.cache(path, query, result);
          } on Object {
            // A cache failure must not turn a successful read into a failed write.
          }
          return local.project(path, result);
        } on ApiException catch (e) {
          if (path == '/workouts/active' && e.code == 'WORKOUT_NOT_FOUND') {
            try {
              await local.cache(path, query, null);
            } on Object {
              /* Keep successful server truth. */
            }
          }

          if (!LocalRecords.transient(e)) rethrow;
          return local.cached(path, query);
        }
      }
    }
    return _onlineRequest(
      method,
      path,
      body: body,
      authenticated: authenticated,
      query: query,
      idempotencyKey: idempotencyKey,
      timeout: timeout,
      refreshAuthentication: refreshAuthentication,
    );
  }

  Future<Object?> _sendRecord(
    String path,
    Map<String, dynamic> body,
    String key,
  ) async {
    final result = await _onlineRequest(
      'POST',
      path,
      body: body,
      idempotencyKey: key,
    );
    final requiredFields = path == '/nutrition/entries'
        ? ['id', 'meal_type', 'eaten_at', 'items', 'totals', 'version']
        : path == '/nutrition/water'
        ? ['id', 'amount_ml', 'consumed_at']
        : path == '/body/measurements'
        ? ['id', 'measured_at', 'version']
        : ['id', 'set_index', 'weight_kg', 'reps', 'completed_at', 'version'];
    if (result is! Map ||
        result['id'] is! String ||
        requiredFields.any((field) => result[field] == null)) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '提交结果尚未完整返回，已保留本机记录等待核对',
      );
    }
    return result;
  }

  Future<void> syncLocalRecords() async {
    await localRecords?.sync(_sendRecord);
  }

  Future<Object?> _onlineRequest(
    String method,
    String path, {
    Object? body,
    bool authenticated = true,
    Map<String, String>? query,
    String? idempotencyKey,
    Duration? timeout,
    bool refreshAuthentication = true,
  }) async {
    if (authenticated && localRecords?.localOnly == true) {
      throw const ApiException(code: 'NETWORK_ERROR', message: '当前离线，请联网后重试');
    }
    final requestScope = localRecords?.accountScope;
    var response = await _send(
      method,
      path,
      body: body,
      authenticated: authenticated,
      query: query,
      idempotencyKey: idempotencyKey,
      timeout: timeout,
    );

    if (authenticated &&
        refreshAuthentication &&
        response.statusCode == HttpStatus.unauthorized &&
        ApiException.fromResponse(response).code !=
            'INVALID_CURRENT_PASSWORD') {
      final refreshed = await _coalescedRefresh();
      if (refreshed) {
        if (requestScope != localRecords?.accountScope) {
          throw const ApiException(
            code: 'LOCAL_ACCOUNT_CHANGED',
            message: '账户已切换，已停止原账户的提交',
          );
        }
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

    if (authenticated &&
        refreshAuthentication &&
        response.statusCode >= 400 &&
        ApiException.fromResponse(response).isAuthenticationFailure) {
      onAuthenticationExpired?.call();
    }

    return _decode(response);
  }

  Stream<SseEvent> postSse(
    String path, {
    required Object body,
    Map<String, String>? query,
    String? idempotencyKey,
  }) async* {
    if (localRecords?.localOnly == true) {
      throw const ApiException(
        code: 'NETWORK_ERROR',
        message: '当前离线，文字草稿已保留，联网后可继续',
      );
    }
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
        if (!retried && response.statusCode == HttpStatus.unauthorized) {
          await _withTimeout(
            response.stream.drain<void>(),
            timeout: requestTimeout,
            abort: abort,
          );
          retried = true;
          if (await _coalescedRefresh()) {
            continue;
          }
          onAuthenticationExpired?.call();
          throw const ApiException(
            code: 'AUTHENTICATION_REQUIRED',
            message: '登录已过期，请重新登录',
          );
        }

        if (response.statusCode < 200 || response.statusCode >= 300) {
          final bytes = await _withTimeout(
            response.stream.toBytes(),
            timeout: requestTimeout,
            abort: abort,
          );
          final error = ApiException.fromResponse(
            http.Response.bytes(
              bytes,
              response.statusCode,
              headers: response.headers,
              reasonPhrase: response.reasonPhrase,
              request: response.request,
            ),
          );
          if (error.isAuthenticationFailure) onAuthenticationExpired?.call();
          throw error;
        }

        final contentType = response.headers['content-type'] ?? '';
        if (!contentType.contains('text/event-stream')) {
          throw const ApiException(
            code: 'INVALID_STREAM_RESPONSE',
            message: '服务器未返回事件流',
          );
        }

        final lines = response.stream
            .transform(utf8.decoder)
            .transform(const LineSplitter());
        yield* parseSseLines(lines).timeout(
          streamProgressTimeout,
          onTimeout: (sink) {
            if (!abort.isCompleted) abort.complete();
            sink.addError(
              const ApiException(
                code: 'REQUEST_TIMEOUT',
                message: 'AI 处理等待超时，已保留收到的内容；请核对待确认草稿后重试',
              ),
            );
            sink.close();
          },
        );
      } on ApiException {
        rethrow;
      } on FormatException {
        rethrow;
      } on Object catch (error) {
        throw ApiException.network(error);
      } finally {
        if (!abort.isCompleted) abort.complete();
      }
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

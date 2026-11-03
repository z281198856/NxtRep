import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/api_exception.dart';

ApiClient buildClient(
  MockClient httpClient, {
  String? Function()? accessTokenProvider,
  Duration requestTimeout = const Duration(seconds: 15),
}) => ApiClient(
  config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
  accessTokenProvider: accessTokenProvider ?? () => null,
  httpClient: httpClient,
  requestTimeout: requestTimeout,
);

void main() {
  group('API response contract', () {
    test('returns direct typed JSON without a data wrapper', () async {
      final client = buildClient(
        MockClient(
          (request) async => http.Response(
            jsonEncode({'username': 'tester'}),
            200,
            headers: {'content-type': 'application/json'},
          ),
        ),
      );

      final result = await client.get('/me', authenticated: false);

      expect(result, {'username': 'tester'});
    });

    test('does not parse a 204 body', () async {
      final client = buildClient(
        MockClient((_) async => http.Response('', 204)),
      );

      expect(await client.post('/auth/logout', authenticated: false), isNull);
    });

    test('branches on the stable error code and preserves details', () async {
      final client = buildClient(
        MockClient(
          (_) async => http.Response(
            jsonEncode({
              'error': {
                'code': 'PROFILE_VERSION_CONFLICT',
                'message': 'Profile has been modified',
                'details': {'current_version': 2},
              },
            }),
            409,
          ),
        ),
      );

      await expectLater(
        client.patch('/profile', body: {'expected_version': 1}),
        throwsA(
          isA<ApiException>()
              .having((error) => error.code, 'code', 'PROFILE_VERSION_CONFLICT')
              .having((error) => error.details, 'details', {
                'current_version': 2,
              }),
        ),
      );
    });

    test('adds idempotency and bearer headers', () async {
      late http.Request captured;
      final client = buildClient(
        MockClient((request) async {
          captured = request;
          return http.Response('{}', 200);
        }),
        accessTokenProvider: () => 'access-token',
      );

      await client.post(
        '/training/sessions',
        body: {'template_id': 'id'},
        idempotencyKey: 'operation-id',
      );

      expect(
        captured.url.toString(),
        'https://api.example.test/api/v1/training/sessions',
      );
      expect(captured.headers['Authorization'], 'Bearer access-token');
      expect(captured.headers['Idempotency-Key'], 'operation-id');
    });
  });

  group('token refresh contract', () {
    test('refreshes and replays a business request only once', () async {
      var accessToken = 'old';
      var refreshCalls = 0;
      var requestCalls = 0;
      final client = buildClient(
        MockClient((request) async {
          requestCalls += 1;
          if (request.headers['Authorization'] == 'Bearer old') {
            return http.Response(
              jsonEncode({
                'error': {
                  'code': 'AUTHENTICATION_REQUIRED',
                  'message': 'expired',
                },
              }),
              401,
            );
          }
          return http.Response(jsonEncode({'ok': true}), 200);
        }),
        accessTokenProvider: () => accessToken,
      );
      client.tokenRefresher = () async {
        refreshCalls += 1;
        accessToken = 'new';
        return true;
      };

      expect(await client.get('/me'), {'ok': true});
      expect(refreshCalls, 1);
      expect(requestCalls, 2);
    });

    test('coalesces simultaneous refresh attempts', () async {
      var accessToken = 'old';
      var refreshCalls = 0;
      final refreshGate = Completer<void>();
      final client = buildClient(
        MockClient((request) async {
          if (request.headers['Authorization'] == 'Bearer old') {
            return http.Response(
              jsonEncode({
                'error': {
                  'code': 'AUTHENTICATION_REQUIRED',
                  'message': 'expired',
                },
              }),
              401,
            );
          }
          return http.Response(jsonEncode({'ok': true}), 200);
        }),
        accessTokenProvider: () => accessToken,
      );
      client.tokenRefresher = () async {
        refreshCalls += 1;
        await refreshGate.future;
        accessToken = 'new';
        return true;
      };

      final first = client.get('/first');
      final second = client.get('/second');
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(refreshCalls, 1);

      refreshGate.complete();
      final results = await Future.wait([first, second]);
      expect(results, everyElement({'ok': true}));
      expect(refreshCalls, 1);
    });
  });

  group('request timeout contract', () {
    for (final status in [401, 503]) {
      test(
        'stalled SSE error body $status is bounded and aborts the connection',
        () async {
          final bytes = StreamController<List<int>>();
          final aborted = Completer<void>();
          final client = ApiClient(
            config: ApiConfig(
              baseUri: Uri.parse('https://api.example.test/api/v1'),
            ),
            accessTokenProvider: () => null,
            requestTimeout: const Duration(milliseconds: 25),
            httpClient: _SseClient((request) async {
              unawaited(
                (request as http.AbortableRequest).abortTrigger!.then((_) {
                  aborted.complete();
                  unawaited(bytes.close());
                }),
              );
              return http.StreamedResponse(bytes.stream, status);
            }),
          );
          addTearDown(client.close);
          await expectLater(
            client.postSse('/agent/chat/stream', body: {}).toList(),
            throwsA(
              isA<ApiException>().having(
                (e) => e.code,
                'code',
                'REQUEST_TIMEOUT',
              ),
            ),
          );
          await aborted.future.timeout(const Duration(seconds: 1));
        },
      );
    }

    test(
      'invalid stream text remains a protocol error instead of a network error',
      () async {
        final client = ApiClient(
          config: ApiConfig(
            baseUri: Uri.parse('https://api.example.test/api/v1'),
          ),
          accessTokenProvider: () => null,
          httpClient: _SseClient(
            (_) async => http.StreamedResponse(
              Stream.value([0xff]),
              200,
              headers: {'content-type': 'text/event-stream'},
            ),
          ),
        );
        addTearDown(client.close);
        await expectLater(
          client.postSse('/agent/chat/stream', body: {}).toList(),
          throwsA(isA<FormatException>()),
        );
      },
    );

    test(
      'SSE heartbeats cannot keep a stalled reply waiting forever',
      () async {
        final bytes = StreamController<List<int>>();
        final aborted = Completer<void>();
        final client = ApiClient(
          config: ApiConfig(
            baseUri: Uri.parse('https://api.example.test/api/v1'),
          ),
          accessTokenProvider: () => null,
          streamProgressTimeout: const Duration(milliseconds: 30),
          httpClient: _SseClient((request) async {
            if (request is http.AbortableRequest) {
              unawaited(
                request.abortTrigger?.then((_) {
                  aborted.complete();
                  unawaited(bytes.close());
                }),
              );
            }
            return http.StreamedResponse(
              bytes.stream,
              200,
              headers: {'content-type': 'text/event-stream'},
            );
          }),
        );
        bytes.add(
          utf8.encode('event: message_delta\ndata: {"delta":"已收到"}\n\n'),
        );
        final heartbeat = Timer.periodic(const Duration(milliseconds: 5), (_) {
          if (!bytes.isClosed) bytes.add(utf8.encode(': heartbeat\n\n'));
        });
        final received = <String>[];
        try {
          await expectLater(
            client
                .postSse('/agent/chat/stream', body: {})
                .forEach((event) => received.add(event.data)),
            throwsA(
              isA<ApiException>().having(
                (error) => error.code,
                'code',
                'REQUEST_TIMEOUT',
              ),
            ),
          );
          expect(received, [contains('已收到')]);
          await aborted.future.timeout(const Duration(seconds: 1));
        } finally {
          heartbeat.cancel();
          await bytes.close();
          client.close();
        }
      },
    );

    test('maps a stalled request to a distinct timeout error', () async {
      final stalled = Completer<http.Response>();
      final client = buildClient(
        MockClient((_) => stalled.future),
        requestTimeout: const Duration(milliseconds: 20),
      );

      await expectLater(
        client.get('/stalled', authenticated: false),
        throwsA(
          isA<ApiException>().having(
            (error) => error.code,
            'code',
            'REQUEST_TIMEOUT',
          ),
        ),
      );
    });

    test('allows a longer timeout for slow vision endpoints', () async {
      final client = buildClient(
        MockClient((_) async {
          await Future<void>.delayed(const Duration(milliseconds: 30));
          return http.Response('{}', 200);
        }),
        requestTimeout: const Duration(milliseconds: 5),
      );

      final result = await client.post(
        '/body/progress-photos/compare',
        authenticated: false,
        timeout: const Duration(milliseconds: 100),
      );

      expect(result, <String, dynamic>{});
    });
  });
}

class _SseClient extends http.BaseClient {
  _SseClient(this.respond);

  final Future<http.StreamedResponse> Function(http.BaseRequest) respond;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) =>
      respond(request);
}

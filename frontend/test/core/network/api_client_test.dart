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
}) => ApiClient(
  config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
  accessTokenProvider: accessTokenProvider ?? () => null,
  httpClient: httpClient,
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
}

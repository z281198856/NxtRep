import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/progress/data/body_repository.dart';
import 'package:nxtrep/features/progress/domain/body_models.dart';

void main() {
  test(
    'sends nullable body fields and pairs manual body fat with its method',
    () async {
      late http.Request captured;
      final client = MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'id': '00000000-0000-0000-0000-000000000051',
            'measured_at': '2026-09-13T03:00:00Z',
            'weight_kg': '72.5',
            'waist_cm': null,
            'body_fat_percent': '18.2',
            'source': 'manual',
            'version': 1,
          }),
          201,
        );
      });
      final repository = BodyRepository(
        ApiClient(
          config: ApiConfig(
            baseUri: Uri.parse('https://api.example.test/api/v1'),
          ),
          accessTokenProvider: () => 'access',
          httpClient: client,
        ),
      );

      final result = await repository.createMeasurement(
        BodyMeasurementInput(
          measuredAt: DateTime.utc(2026, 9, 13, 3),
          weightKg: 72.5,
          bodyFatPercent: 18.2,
        ),
      );
      final body = jsonDecode(captured.body) as Map<String, dynamic>;

      expect(captured.url.path, '/api/v1/body/measurements');
      expect(captured.headers['Idempotency-Key'], isNotEmpty);
      expect(body['body_fat_percent'], 18.2);
      expect(body['body_fat_method'], 'manual');
      expect(body['waist_cm'], isNull);
      expect(result.weightKg, 72.5);
    },
  );

  test(
    'loads overview, trend and personal records from progress APIs',
    () async {
      final client = MockClient((request) async {
        if (request.url.path.endsWith('/progress/overview')) {
          return http.Response(
            jsonEncode({
              'training': {
                'workout_count': 4,
                'completion_rate': '0.75',
                'total_duration_minutes': 160,
                'pr_count': 2,
              },
              'nutrition': {},
              'body': {
                'weight_start_kg': '72.5',
                'weight_end_kg': '71.8',
                'smoothed_change_kg': '-0.7',
              },
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/progress/body-trend')) {
          return http.Response(
            jsonEncode({
              'metric': 'weight',
              'window': '7d',
              'points': [
                {
                  'date': '2026-09-01',
                  'raw_value': '72.5',
                  'smoothed_value': '72.5',
                },
                {
                  'date': '2026-09-13',
                  'raw_value': '71.8',
                  'smoothed_value': '72.15',
                },
              ],
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/progress/prs')) {
          return http.Response(
            jsonEncode({
              'list': [
                {
                  'id': '00000000-0000-0000-0000-000000000061',
                  'exercise_id': '00000000-0000-0000-0000-000000000062',
                  'exercise_name': '杠铃深蹲',
                  'record_type': 'max_weight',
                  'value': '80.0',
                  'occurred_at': '2026-09-13T03:00:00Z',
                  'workout_id': '00000000-0000-0000-0000-000000000063',
                  'set_id': '00000000-0000-0000-0000-000000000064',
                },
              ],
              'total': 1,
              'page': 1,
              'page_size': 20,
              'has_more': false,
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('not found', 404);
      });
      final repository = BodyRepository(
        ApiClient(
          config: ApiConfig(
            baseUri: Uri.parse('https://api.example.test/api/v1'),
          ),
          accessTokenProvider: () => 'access',
          httpClient: client,
        ),
      );

      final overview = await repository.getOverview(days: 30);
      final trend = await repository.getBodyTrend(
        metric: BodyMetric.weight,
        days: 30,
      );
      final records = await repository.listPersonalRecords();

      expect(overview.training.workoutCount, 4);
      expect(overview.training.completionRate, 0.75);
      expect(overview.body.smoothedChangeKg, -0.7);
      expect(trend, hasLength(2));
      expect(trend.last.smoothedValue, 72.15);
      expect(records.single.exerciseName, '杠铃深蹲');
    },
  );

  test('updates a measurement with its optimistic-lock version', () async {
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        jsonEncode({
          'id': '00000000-0000-0000-0000-000000000071',
          'measured_at': '2026-09-13T03:00:00Z',
          'weight_kg': '71.9',
          'waist_cm': '78.0',
          'neck_cm': null,
          'hip_cm': null,
          'body_fat_percent': null,
          'body_fat_method': null,
          'source': 'manual',
          'conditions': '晨起空腹',
          'notes': null,
          'version': 3,
        }),
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    });
    final repository = BodyRepository(
      ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: client,
      ),
    );
    final current = BodyMeasurement.fromJson({
      'id': '00000000-0000-0000-0000-000000000071',
      'measured_at': '2026-09-12T03:00:00Z',
      'weight_kg': '72.1',
      'waist_cm': null,
      'source': 'manual',
      'version': 2,
    });

    final updated = await repository.updateMeasurement(
      current,
      BodyMeasurementInput(
        measuredAt: DateTime.utc(2026, 9, 13, 3),
        weightKg: 71.9,
        waistCm: 78,
        conditions: '晨起空腹',
      ),
    );
    final body = jsonDecode(captured.body) as Map<String, dynamic>;

    expect(captured.method, 'PATCH');
    expect(body['expected_version'], 2);
    expect(body['reason'], '用户修改身体测量记录');
    expect(updated.version, 3);
    expect(updated.waistCm, 78);
  });
}

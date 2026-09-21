import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/core/network/api_exception.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/domain/training_models.dart';

Map<String, dynamic> workoutJson() => {
  'id': '00000000-0000-0000-0000-000000000010',
  'status': 'in_progress',
  'started_at': '2026-09-13T01:00:00Z',
  'elapsed_seconds': 20,
  'rest_timer': null,
  'version': 4,
  'exercises': [
    {
      'id': '00000000-0000-0000-0000-000000000011',
      'exercise_id': '00000000-0000-0000-0000-000000000012',
      'name_snapshot': '杠铃深蹲',
      'target_snapshot': {
        'target_sets': 3,
        'rep_min': 6,
        'rep_max': 8,
        'rest_seconds': 120,
      },
      'skipped': false,
      'sets': [],
    },
  ],
};

void main() {
  test(
    'loads calendar with required date range and handles no active workout',
    () async {
      final client = MockClient((request) async {
        if (request.url.path == '/api/v1/calendar') {
          expect(request.url.queryParameters, {
            'start_date': '2026-09-13',
            'end_date': '2026-09-13',
          });
          return http.Response(
            jsonEncode([
              {
                'id': '00000000-0000-0000-0000-000000000001',
                'scheduled_date': '2026-09-13',
                'status': 'planned',
                'plan_day_id': '00000000-0000-0000-0000-000000000002',
                'title': '下肢训练',
                'estimated_minutes': 60,
                'actual_workout_id': null,
              },
            ]),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.url.path == '/api/v1/workouts/active') {
          return http.Response(
            jsonEncode({
              'error': {
                'code': 'WORKOUT_NOT_FOUND',
                'message': 'Workout not found',
              },
            }),
            404,
          );
        }
        throw StateError('Unexpected request ${request.url}');
      });
      final api = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: client,
      );
      final repository = TrainingRepository(api);

      final events = await repository.getCalendar(
        DateTime(2026, 9, 13),
        DateTime(2026, 9, 13),
      );

      expect(events.single.title, '下肢训练');
      expect(await repository.getActiveWorkout(), isNull);
    },
  );

  test(
    'uses one stable client UUID for set identity and idempotency',
    () async {
      late http.Request captured;
      final client = MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'id': '00000000-0000-0000-0000-000000000020',
            'set_index': 1,
            'weight_kg': '80.000',
            'reps': 8,
            'completed_at': '2026-09-13T01:05:00Z',
            'version': 1,
          }),
          201,
        );
      });
      final api = ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: client,
      );
      final repository = TrainingRepository(api);
      final workout = Workout.fromJson(workoutJson());

      final result = await repository.createSet(
        workout: workout,
        exercise: workout.exercises.single,
        weightKg: 80,
        reps: 8,
      );
      final body = jsonDecode(captured.body) as Map<String, dynamic>;

      expect(captured.method, 'POST');
      expect(captured.url.path, '/api/v1/workouts/${workout.id}/sets');
      expect(captured.headers['Idempotency-Key'], body['client_generated_id']);
      expect(body['workout_exercise_id'], workout.exercises.single.id);
      expect(body['set_index'], 1);
      expect(body['weight_kg'], 80.0);
      expect(body['reps'], 8);
      expect(DateTime.parse(body['completed_at'] as String).isUtc, isTrue);
      expect(result.weightKg, 80);
    },
  );

  test('activates an official template through validation and confirmation', () async {
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      switch ('${request.method} ${request.url.path}') {
        case 'GET /api/v1/training/templates':
          return http.Response(
            jsonEncode([
              {
                'id': '20000000-0000-4000-8000-000000000001',
                'name': '三天全身训练',
                'goal_types': ['muscle_gain', 'strength'],
                'days_per_week': 3,
                'duration_minutes': 60,
              },
            ]),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        case 'POST /api/v1/training/plan-drafts/from-template':
          return http.Response(
            jsonEncode({
              'id': '30000000-0000-4000-8000-000000000001',
              'name': '三天全身训练',
              'status': 'editing',
              'version': 1,
              'weekly_frequency': 3,
              'days': [
                {
                  'id': '40000000-0000-4000-8000-000000000001',
                  'day_index': 1,
                  'name': '训练A',
                  'estimated_minutes': 60,
                  'exercises': [],
                },
              ],
            }),
            201,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        case 'POST /api/v1/training/plan-drafts/30000000-0000-4000-8000-000000000001/validate':
          return http.Response(
            jsonEncode({
              'valid': true,
              'errors': [],
              'warnings': [],
              'estimated_weekly_minutes': 180,
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        case 'POST /api/v1/training/plan-drafts/30000000-0000-4000-8000-000000000001/submit':
          return http.Response(
            jsonEncode({
              'confirmation_id': '50000000-0000-4000-8000-000000000001',
              'operation_type': 'training_plan_activate',
              'status': 'pending',
              'before': null,
              'after': const <String, dynamic>{},
              'impact': '未来日历使用新计划，历史训练不变',
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        case 'GET /api/v1/confirmations/50000000-0000-4000-8000-000000000001':
          return http.Response(
            jsonEncode({
              'id': '50000000-0000-4000-8000-000000000001',
              'status': 'pending',
              'version': 1,
            }),
            200,
          );
        case 'POST /api/v1/confirmations/50000000-0000-4000-8000-000000000001/approve':
          return http.Response(
            jsonEncode({
              'id': '50000000-0000-4000-8000-000000000001',
              'status': 'succeeded',
              'result': const <String, dynamic>{},
              'executed_at': '2026-09-20T02:00:00Z',
              'version': 2,
            }),
            200,
          );
        case 'GET /api/v1/training/plans/active':
          return http.Response(
            jsonEncode({
              'id': '60000000-0000-4000-8000-000000000001',
              'plan_id': '70000000-0000-4000-8000-000000000001',
              'name': '三天全身训练',
              'version': 1,
              'weekly_frequency': 3,
              'days': [
                {
                  'id': '40000000-0000-4000-8000-000000000001',
                  'day_index': 1,
                  'name': '训练A',
                  'estimated_minutes': 60,
                  'exercises': [],
                },
              ],
              'activated_at': '2026-09-20T02:00:00Z',
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
      }
      return http.Response(
        jsonEncode({
          'error': {
            'code': 'UNEXPECTED_REQUEST',
            'message': '${request.method} ${request.url.path}',
          },
        }),
        500,
      );
    });
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: client,
    );
    final repository = TrainingRepository(api);

    late ActiveTrainingPlan plan;
    try {
      final template = (await repository.getTemplates()).single;
      plan = await repository.activateTemplate(template);
    } on ApiException catch (error) {
      fail('activation request failed: ${error.details ?? error}');
    }

    expect(plan.name, '三天全身训练');
    expect(plan.days.single.name, '训练A');
    expect(requests, hasLength(7));
    final approval = requests[5];
    expect(approval.headers['Idempotency-Key'], isNotEmpty);
    expect(jsonDecode(approval.body), {'expected_version': 1});
  });

  test('loads workout history summaries', () async {
    final client = MockClient((request) async {
      expect(request.url.path, '/api/v1/workouts');
      expect(request.url.queryParameters, {'page': '1', 'page_size': '20'});
      return http.Response(
        jsonEncode({
          'list': [
            {
              'id': '00000000-0000-0000-0000-000000000030',
              'date': '2026-09-20',
              'status': 'finished',
              'duration_seconds': 1800,
              'completed_sets': 9,
              'total_volume_kg': '2450.000',
              'pr_count': 1,
            },
          ],
          'total': 1,
          'page': 1,
          'page_size': 20,
          'has_more': false,
        }),
        200,
      );
    });
    final repository = TrainingRepository(
      ApiClient(
        config: ApiConfig(
          baseUri: Uri.parse('https://api.example.test/api/v1'),
        ),
        accessTokenProvider: () => 'access',
        httpClient: client,
      ),
    );

    final page = await repository.getWorkoutHistory();

    expect(page.total, 1);
    expect(page.items.single.completedSets, 9);
    expect(page.items.single.totalVolumeKg, 2450);
    expect(page.items.single.prCount, 1);
  });
}

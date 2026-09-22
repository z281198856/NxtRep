import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/exercises/data/exercise_repository.dart';
import 'package:nxtrep/features/exercises/domain/exercise_models.dart';

void main() {
  ExerciseRepository repositoryWith(MockClient client) => ExerciseRepository(
    ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: client,
    ),
  );

  test('lists exercises with search and equipment filters', () async {
    late http.Request captured;
    final repository = repositoryWith(
      MockClient((request) async {
        captured = request;
        return _utf8Response(
          jsonEncode({
            'list': [
              {
                'id': '00000000-0000-0000-0000-000000000101',
                'name_zh': '杠铃深蹲',
                'aliases': ['深蹲'],
                'equipment': 'barbell',
                'primary_muscles': ['quadriceps', 'gluteus'],
                'is_custom': false,
              },
            ],
            'total': 1,
            'page': 1,
            'page_size': 100,
            'has_more': false,
          }),
          200,
        );
      }),
    );

    final result = await repository.list(keyword: ' 深蹲 ', equipment: 'barbell');

    expect(captured.url.path, '/api/v1/exercises');
    expect(captured.url.queryParameters['keyword'], '深蹲');
    expect(captured.url.queryParameters['equipment'], 'barbell');
    expect(captured.url.queryParameters['page_size'], '100');
    expect(result.items.single.name, '杠铃深蹲');
    expect(result.items.single.primaryMuscles, contains('quadriceps'));
  });

  test('loads exercise detail and training history', () async {
    final repository = repositoryWith(
      MockClient((request) async {
        if (request.url.path.endsWith('/history')) {
          return _utf8Response(
            jsonEncode({
              'exercise_id': '00000000-0000-0000-0000-000000000101',
              'history': [
                {
                  'workout_id': '00000000-0000-0000-0000-000000000201',
                  'started_at': '2026-09-21T10:00:00Z',
                  'status': 'completed',
                  'name_snapshot': '杠铃深蹲',
                  'sets': [
                    {
                      'set_index': 1,
                      'weight_kg': '80.0',
                      'reps': 5,
                      'rir': 2,
                      'rpe': '8.0',
                      'completed_at': '2026-09-21T10:15:00Z',
                    },
                  ],
                },
              ],
            }),
            200,
          );
        }
        return _utf8Response(jsonEncode(_exerciseDetail()), 200);
      }),
    );

    final detail = await repository.getDetail(
      '00000000-0000-0000-0000-000000000101',
    );
    final history = await repository.getHistory(detail.id);

    expect(detail.instructions, ['保持脊柱中立', '下蹲后站起']);
    expect(detail.substitutions.single.name, '哑铃高脚杯深蹲');
    expect(history.single.sets.single.weightKg, 80);
    expect(history.single.sets.single.reps, 5);
  });

  test('creates, updates, and deletes a custom exercise', () async {
    final requests = <http.Request>[];
    var version = 1;
    final repository = repositoryWith(
      MockClient((request) async {
        requests.add(request);
        if (request.method == 'DELETE') return _utf8Response('', 204);
        if (request.method == 'PATCH') version = 2;
        return _utf8Response(
          jsonEncode(
            _exerciseDetail(
              name: request.method == 'PATCH' ? '单臂划船 2' : '单臂划船',
              isCustom: true,
              version: version,
            ),
          ),
          request.method == 'POST' ? 201 : 200,
        );
      }),
    );
    const input = CustomExerciseInput(
      name: '单臂划船',
      equipment: 'dumbbell',
      primaryMuscles: ['back'],
      secondaryMuscles: ['biceps'],
      notes: '保持躯干稳定',
    );

    final created = await repository.create(input);
    final updated = await repository.update(
      created,
      const CustomExerciseInput(
        name: '单臂划船 2',
        equipment: 'dumbbell',
        primaryMuscles: ['back'],
        secondaryMuscles: ['biceps'],
        notes: '慢速离心',
      ),
    );
    await repository.delete(updated);

    expect(requests[0].headers['Idempotency-Key'], isNotEmpty);
    expect(jsonDecode(requests[1].body)['expected_version'], 1);
    expect(requests[2].url.queryParameters['expected_version'], '2');
    expect(updated.version, 2);
  });
}

Map<String, dynamic> _exerciseDetail({
  String name = '杠铃深蹲',
  bool isCustom = false,
  int version = 1,
}) => {
  'id': '00000000-0000-0000-0000-000000000101',
  'name_zh': name,
  'aliases': ['深蹲'],
  'movement_pattern': 'squat',
  'equipment': isCustom ? 'dumbbell' : 'barbell',
  'difficulty': 'intermediate',
  'primary_muscles': ['quadriceps', 'gluteus'],
  'secondary_muscles': ['core'],
  'instructions': ['保持脊柱中立', '下蹲后站起'],
  'breathing': ['下蹲吸气', '站起呼气'],
  'common_errors': ['膝盖内扣'],
  'safety_notes': ['从可控重量开始'],
  'substitutions': [
    {
      'id': '00000000-0000-0000-0000-000000000102',
      'name_zh': '哑铃高脚杯深蹲',
      'equipment': 'dumbbell',
      'reason': '器械要求更低',
    },
  ],
  'notes': null,
  'version': version,
  'is_custom': isCustom,
};

http.Response _utf8Response(String body, int statusCode) => http.Response.bytes(
  utf8.encode(body),
  statusCode,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

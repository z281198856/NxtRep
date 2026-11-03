import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/core/settings/app_preferences.dart';
import 'package:nxtrep/features/profile/domain/profile_models.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/exercises/data/exercise_repository.dart';
import 'package:nxtrep/features/training/data/training_repository.dart';
import 'package:nxtrep/features/training/domain/training_models.dart';
import 'package:nxtrep/features/training/presentation/training_controller.dart';
import 'package:nxtrep/features/training/presentation/workout_page.dart';

class _WorkoutApi {
  _WorkoutApi({bool planned = false, bool empty = false}) {
    workout = {
      'id': 'workout-1',
      'status': 'in_progress',
      'version': 1,
      'calendar_event_id': planned ? 'event-1' : null,
      'started_at': DateTime.now()
          .toUtc()
          .subtract(const Duration(minutes: 5))
          .toIso8601String(),
      'elapsed_seconds': 300,
      'rest_timer': null,
      'exercises': empty
          ? <Map<String, dynamic>>[]
          : [
              {
                'id': 'item-1',
                'exercise_id': 'bench',
                'name_snapshot': '卧推',
                'target_snapshot': {
                  'sets': 4,
                  'rep_min': 8,
                  'rep_max': 12,
                  'rest_seconds': 90,
                },
                'skipped': false,
                'sets': <Map<String, dynamic>>[],
              },
            ],
    };
    api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://test/api/v1')),
      accessTokenProvider: () => 'test',
      httpClient: MockClient(_handle),
    );
    controller = TrainingController(TrainingRepository(api))
      ..activeWorkout = Workout.fromJson(workout);
  }

  late final Map<String, dynamic> workout;
  late final ApiClient api;
  late final TrainingController controller;
  final requests = <http.Request>[];
  bool failSet = false;

  http.Response _response(Object body, [int status = 200]) => http.Response(
    jsonEncode(body),
    status,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );

  Future<http.Response> _handle(http.Request request) async {
    requests.add(request);
    final path = request.url.path;
    final exercises = workout['exercises'] as List;
    if (request.method == 'PATCH' && path.endsWith('/target')) {
      final body = jsonDecode(request.body) as Map;
      final target = exercises.first['target_snapshot'] as Map;
      if (body.containsKey('target_sets')) target['sets'] = body['target_sets'];
      if (body.containsKey('rest_seconds')) {
        target['rest_seconds'] = body['rest_seconds'];
      }
      workout['version'] = (workout['version'] as int) + 1;
      return _response(workout);
    }
    if (request.method == 'POST' && path.endsWith('/sets')) {
      if (failSet) {
        return _response({
          'error': {'code': 'TEST_FAILURE', 'message': '这一组没有保存成功'},
        }, 503);
      }
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final set = {...body, 'id': 'set-1', 'version': 1};
      (exercises.first['sets'] as List).add(set);
      workout['rest_timer'] = {
        'workout_exercise_id': 'item-1',
        'duration_seconds': exercises.first['target_snapshot']['rest_seconds'],
        'ends_at': DateTime.now()
            .toUtc()
            .add(
              Duration(
                seconds:
                    exercises.first['target_snapshot']['rest_seconds'] as int,
              ),
            )
            .toIso8601String(),
      };
      return _response(set, 201);
    }
    if (path.endsWith('/workouts/active')) return _response(workout);
    if (request.method == 'GET' && path.endsWith('/exercises')) {
      return _response({
        'list': [
          {
            'id': 'incline',
            'name_zh': '上斜哑铃卧推',
            'equipment': 'dumbbell',
            'primary_muscles': ['chest'],
            'aliases': [],
          },
        ],
        'total': 1,
        'has_more': false,
      });
    }
    if (request.method == 'POST' && path.endsWith('/exercises')) {
      final body = jsonDecode(request.body) as Map;
      exercises.add({
        'id': 'item-2',
        'exercise_id': body['exercise_id'],
        'name_snapshot': '上斜哑铃卧推',
        'target_snapshot': {
          'sets': body['target_sets'],
          'rep_min': 8,
          'rep_max': 12,
          'rest_seconds': body['rest_seconds'],
        },
        'skipped': false,
        'sets': <Map<String, dynamic>>[],
      });
      return _response(workout, 201);
    }
    throw StateError('Unexpected ${request.method} $path');
  }

  Future<void> mount(WidgetTester tester, {bool imperial = false}) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(() {
      controller.dispose();
      api.close();
    });
    await tester.pumpWidget(
      AppPreferencesScope(
        settings: AppSettings(
          unitSystem: imperial ? 'imperial' : 'metric',
          timezone: 'Asia/Shanghai',
          privacyMode: 'private',
          shareAnonymousAnalytics: false,
          version: 1,
        ),
        child: MaterialApp(
          home: WorkoutPage(
            controller: controller,
            exerciseRepository: ExerciseRepository(api),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }
}

void main() {
  testWidgets('imperial workout entry stores kg and displays lb', (
    tester,
  ) async {
    final state = _WorkoutApi();
    await state.mount(tester, imperial: true);
    await tester.tap(find.text('完成下一组'));
    await tester.pumpAndSettle();
    expect(find.text('重量（lb）'), findsOneWidget);
    await tester.enterText(find.byType(TextFormField).first, '110');
    await tester.enterText(find.byType(TextFormField).last, '8');
    await tester.tap(find.text('完成这一组'));
    await tester.pumpAndSettle();
    final body = jsonDecode(
      state.requests.firstWhere((r) => r.url.path.endsWith('/sets')).body,
    ) as Map;
    expect(body['weight_kg'], closeTo(49.8951607, 1e-7));
    expect(find.text('110.0 lb'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'planned targets can be changed and saved without replacing the plan',
    (tester) async {
      final state = _WorkoutApi(planned: true);
      await state.mount(tester);
      expect(find.text('计划训练'), findsOneWidget);
      expect(find.text('0/4 组'), findsOneWidget);
      await tester.tap(find.text('0/4 组'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField), '6');
      await tester.tap(find.text('保存'));
      await tester.pumpAndSettle();
      expect(find.text('0/6 组'), findsOneWidget);
      final request = state.requests.single;
      expect(jsonDecode(request.body), {
        'target_sets': 6,
        'expected_workout_version': 1,
      });
      expect(
        request.url.path,
        '/api/v1/workouts/workout-1/exercises/item-1/target',
      );
      expect(find.text('临时添加动作'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'rest duration accepts custom seconds and recording starts the adjacent timer',
    (tester) async {
      final state = _WorkoutApi();
      await state.mount(tester);
      await tester.tap(find.text('休息时长'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField), '75');
      await tester.tap(find.text('保存'));
      await tester.pumpAndSettle();
      expect(find.text('01:15'), findsOneWidget);
      await tester.tap(find.text('完成下一组'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField).first, '55');
      await tester.enterText(find.byType(TextFormField).last, '8');
      await tester.tap(find.text('完成这一组'));
      await tester.pumpAndSettle();
      expect(find.text('1/4 组'), findsOneWidget);
      expect(find.text('组间休息'), findsOneWidget);
      expect(
        (tester.getTopLeft(find.text('总用时')).dy -
                tester.getTopLeft(find.text('组间休息')).dy)
            .abs(),
        lessThan(25),
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'self training adds first and next exercises without copying completed sets',
    (tester) async {
      final state = _WorkoutApi(empty: true);
      await state.mount(tester);
      expect(find.text('自主训练'), findsOneWidget);
      expect(find.text('临时添加动作'), findsNothing);
      await tester.tap(find.text('添加第一个动作'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('上斜哑铃卧推'));
      await tester.pumpAndSettle();
      expect(find.text('下一个动作'), findsOneWidget);
      expect(find.text('0/3 组'), findsOneWidget);
      final body = jsonDecode(state.requests.last.body) as Map;
      expect(body['target_load_kg'], isNull);
      expect(state.controller.activeWorkout!.completedSetCount, 0);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'completed exercise allows increasing the target to record another set',
    (tester) async {
      final state = _WorkoutApi();
      final exercise = (state.workout['exercises'] as List).first as Map;
      exercise['target_snapshot']['sets'] = 1;
      exercise['sets'].add({
        'id': 'set-1',
        'set_index': 1,
        'weight_kg': 55,
        'reps': 8,
        'completed_at': DateTime.now().toUtc().toIso8601String(),
        'version': 1,
      });
      state.controller.activeWorkout = Workout.fromJson(state.workout);
      await state.mount(tester);
      expect(find.text('已完成'), findsOneWidget);
      await tester.tap(find.text('1/1 组'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField), '2');
      await tester.tap(find.text('保存'));
      await tester.pumpAndSettle();
      expect(find.text('完成下一组'), findsOneWidget);
      expect(state.controller.activeWorkout!.completedSetCount, 1);
    },
  );

  testWidgets('failed set save keeps completion and rest timer unchanged', (
    tester,
  ) async {
    final state = _WorkoutApi()..failSet = true;
    await state.mount(tester);
    await tester.tap(find.text('完成下一组'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('完成这一组'));
    await tester.pumpAndSettle();
    expect(find.text('0/4 组'), findsOneWidget);
    expect(find.text('组间休息'), findsNothing);
    expect(find.text('这一组没有保存成功'), findsOneWidget);
  });

  test(
    'workout target supports server snapshots and the previous client field',
    () {
      final server = _WorkoutApi();
      expect(server.controller.activeWorkout!.exercises.single.targetSets, 4);
      expect(
        const WorkoutExercise(
          id: 'old',
          name: '旧动作',
          target: {'target_sets': 5},
          skipped: false,
          sets: [],
        ).targetSets,
        5,
      );
      server.controller.dispose();
      server.api.close();
    },
  );
}

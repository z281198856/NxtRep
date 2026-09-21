import 'package:uuid/uuid.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/api_exception.dart';
import '../domain/training_models.dart';

class TrainingRepository {
  TrainingRepository(this._apiClient, {Uuid? uuid})
    : _uuid = uuid ?? const Uuid();

  final ApiClient _apiClient;
  final Uuid _uuid;

  Future<List<TrainingTemplate>> getTemplates() async {
    final value = await _apiClient.get('/training/templates');
    if (value is! List<dynamic>) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '官方训练计划返回格式不正确',
      );
    }
    return value
        .map((item) => TrainingTemplate.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<ActiveTrainingPlan> activateTemplate(TrainingTemplate template) async {
    final draft = PlanDraft.fromJson(
      expectJsonObject(
        await _apiClient.post(
          '/training/plan-drafts/from-template',
          idempotencyKey: _uuid.v4(),
          body: {'template_id': template.id, 'name': template.name},
        ),
        context: '创建训练计划草稿接口',
      ),
    );
    final validation = PlanValidation.fromJson(
      expectJsonObject(
        await _apiClient.post(
          '/training/plan-drafts/${draft.id}/validate',
          body: {'expected_version': draft.version},
        ),
        context: '训练计划校验接口',
      ),
    );
    if (!validation.valid) {
      throw ApiException(
        code: 'TRAINING_PLAN_INVALID',
        message: '该计划暂时无法启用，请稍后重试',
        details: validation.errors,
      );
    }

    final confirmation = PlanConfirmation.fromSubmitJson(
      expectJsonObject(
        await _apiClient.post(
          '/training/plan-drafts/${draft.id}/submit',
          idempotencyKey: _uuid.v4(),
          body: {'expected_version': draft.version},
        ),
        context: '提交训练计划接口',
      ),
    );
    final confirmationDetails = ConfirmationDetails.fromJson(
      expectJsonObject(
        await _apiClient.get('/confirmations/${confirmation.id}'),
        context: '训练计划确认接口',
      ),
    );
    final decision = expectJsonObject(
      await _apiClient.post(
        '/confirmations/${confirmation.id}/approve',
        idempotencyKey: _uuid.v4(),
        body: {'expected_version': confirmationDetails.version},
      ),
      context: '启用训练计划接口',
    );
    if (decision['status'] != 'succeeded') {
      throw const ApiException(
        code: 'TRAINING_PLAN_ACTIVATION_FAILED',
        message: '训练计划未能成功启用',
      );
    }
    final active = await getActivePlan();
    if (active == null) {
      throw const ApiException(
        code: 'TRAINING_PLAN_ACTIVATION_FAILED',
        message: '训练计划已确认，但暂时无法读取',
      );
    }
    return active;
  }

  Future<ActiveTrainingPlan?> getActivePlan() async {
    try {
      final json = expectJsonObject(
        await _apiClient.get('/training/plans/active'),
        context: '当前训练计划接口',
      );
      return ActiveTrainingPlan.fromJson(json);
    } on ApiException catch (error) {
      if (error.code == 'ACTIVE_PLAN_NOT_FOUND') return null;
      rethrow;
    }
  }

  Future<List<CalendarEvent>> getCalendar(DateTime start, DateTime end) async {
    final value = await _apiClient.get(
      '/calendar',
      query: {'start_date': _dateOnly(start), 'end_date': _dateOnly(end)},
    );
    if (value is! List<dynamic>) {
      throw const ApiException(
        code: 'INVALID_SUCCESS_RESPONSE',
        message: '训练日历返回格式不正确',
      );
    }
    return value
        .map((item) => CalendarEvent.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<Workout?> getActiveWorkout() async {
    try {
      final json = expectJsonObject(
        await _apiClient.get('/workouts/active'),
        context: '当前训练接口',
      );
      return Workout.fromJson(json);
    } on ApiException catch (error) {
      if (error.code == 'WORKOUT_NOT_FOUND') return null;
      rethrow;
    }
  }

  Future<WorkoutHistoryPageData> getWorkoutHistory({
    int page = 1,
    int pageSize = 20,
  }) async {
    final json = expectJsonObject(
      await _apiClient.get(
        '/workouts',
        query: {'page': '$page', 'page_size': '$pageSize'},
      ),
      context: '训练历史接口',
    );
    return WorkoutHistoryPageData.fromJson(json);
  }

  Future<Workout> getWorkout(String workoutId) async {
    final json = expectJsonObject(
      await _apiClient.get('/workouts/$workoutId'),
      context: '训练详情接口',
    );
    return Workout.fromJson(json);
  }

  Future<Workout> startWorkout(CalendarEvent event) async {
    final operationId = _uuid.v4();
    final json = expectJsonObject(
      await _apiClient.post(
        '/workouts',
        idempotencyKey: operationId,
        body: {
          'calendar_event_id': event.id,
          'plan_day_id': event.planDayId,
          'started_at': DateTime.now().toUtc().toIso8601String(),
          'pre_check': null,
        },
      ),
      context: '开始训练接口',
    );
    return Workout.fromJson(json);
  }

  Future<WorkoutSet> createSet({
    required Workout workout,
    required WorkoutExercise exercise,
    required double weightKg,
    required int reps,
  }) async {
    final clientGeneratedId = _uuid.v4();
    final json = expectJsonObject(
      await _apiClient.post(
        '/workouts/${workout.id}/sets',
        idempotencyKey: clientGeneratedId,
        body: {
          'client_generated_id': clientGeneratedId,
          'workout_exercise_id': exercise.id,
          'set_index': exercise.sets.length + 1,
          'weight_kg': weightKg,
          'reps': reps,
          'rir': null,
          'rpe': null,
          'tags': const <String>[],
          'notes': null,
          'completed_at': DateTime.now().toUtc().toIso8601String(),
        },
      ),
      context: '训练组记录接口',
    );
    return WorkoutSet.fromJson(json);
  }

  Future<Workout> pauseWorkout(Workout workout) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/workouts/${workout.id}/pause',
        idempotencyKey: _uuid.v4(),
        body: {
          'paused_at': DateTime.now().toUtc().toIso8601String(),
          'expected_version': workout.version,
        },
      ),
      context: '暂停训练接口',
    );
    return Workout.fromJson(json);
  }

  Future<Workout> resumeWorkout(Workout workout) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/workouts/${workout.id}/resume',
        idempotencyKey: _uuid.v4(),
        body: {
          'resumed_at': DateTime.now().toUtc().toIso8601String(),
          'expected_version': workout.version,
        },
      ),
      context: '继续训练接口',
    );
    return Workout.fromJson(json);
  }

  Future<WorkoutFinishSummary> finishWorkout(
    Workout workout, {
    int? overallDifficulty,
    int? fatigue,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/workouts/${workout.id}/finish',
        idempotencyKey: _uuid.v4(),
        body: {
          'ended_at': DateTime.now().toUtc().toIso8601String(),
          'overall_difficulty': overallDifficulty,
          'fatigue': fatigue,
          'pain': const <Object>[],
          'interruption_reason': null,
          'expected_version': workout.version,
        },
      ),
      context: '结束训练接口',
    );
    return WorkoutFinishSummary.fromJson(json);
  }

  String _dateOnly(DateTime value) {
    final year = value.year.toString().padLeft(4, '0');
    final month = value.month.toString().padLeft(2, '0');
    final day = value.day.toString().padLeft(2, '0');
    return '$year-$month-$day';
  }
}

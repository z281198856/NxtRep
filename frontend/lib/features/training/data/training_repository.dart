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
    return activateDraft(draft);
  }

  Future<PlanDraft> generatePlanDraft({
    required String goalType,
    required int daysPerWeek,
    required String equipment,
    String? name,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/training/plan-drafts:generate',
        idempotencyKey: _uuid.v4(),
        body: {
          'goal_type': goalType,
          'days_per_week': daysPerWeek,
          'equipment': equipment,
          'name': name,
        },
      ),
      context: 'AI 生成训练计划接口',
    );
    return PlanDraft.fromJson(json);
  }

  Future<PlanDraft> parsePlanText({required String text, String? name}) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/training/plan-drafts:parse-text',
        idempotencyKey: _uuid.v4(),
        body: {'text': text.trim(), 'template_id': null, 'name': name},
      ),
      context: '文字导入训练计划接口',
    );
    return PlanDraft.fromJson(json);
  }

  Future<ActiveTrainingPlan> activateDraft(PlanDraft draft) async {
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

  Future<CalendarEvent> createCalendarEvent({
    required DateTime date,
    required String title,
    required int estimatedMinutes,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/calendar/events',
        idempotencyKey: _uuid.v4(),
        body: {
          'scheduled_date': _dateOnly(date),
          'title': title.trim(),
          'estimated_minutes': estimatedMinutes,
          'exercises': const <Object>[],
        },
      ),
      context: '新建日历训练接口',
    );
    return CalendarEvent.fromJson(json);
  }

  Future<CalendarAdjustmentDraft> rescheduleEvent({
    required CalendarEvent event,
    required String strategy,
    DateTime? targetDate,
    String? reason,
  }) async {
    final draft = CalendarAdjustmentDraft.fromJson(
      expectJsonObject(
        await _apiClient.post(
          '/calendar/reschedule-drafts',
          idempotencyKey: _uuid.v4(),
          body: {
            'missed_event_id': event.id,
            'strategy': strategy,
            'target_date': targetDate == null ? null : _dateOnly(targetDate),
            'reason': reason,
          },
        ),
        context: '训练改期草稿接口',
      ),
    );
    await _submitAndApproveCalendarDraft(draft);
    return draft;
  }

  Future<CalendarAdjustmentDraft> compressEvent({
    required CalendarEvent event,
    required int targetMinutes,
    String? reason,
  }) async {
    final draft = CalendarAdjustmentDraft.fromJson(
      expectJsonObject(
        await _apiClient.post(
          '/calendar/compression-drafts',
          idempotencyKey: _uuid.v4(),
          body: {
            'event_id': event.id,
            'target_minutes': targetMinutes,
            'reason': reason,
          },
        ),
        context: '训练压缩草稿接口',
      ),
    );
    await _submitAndApproveCalendarDraft(draft);
    return draft;
  }

  Future<void> _submitAndApproveCalendarDraft(
    CalendarAdjustmentDraft draft,
  ) async {
    final submitted = PlanConfirmation.fromSubmitJson(
      expectJsonObject(
        await _apiClient.post(
          '/calendar/reschedule-drafts/${draft.id}/submit',
          idempotencyKey: _uuid.v4(),
          body: {'expected_version': draft.version},
        ),
        context: '提交日历调整接口',
      ),
    );
    await _approveConfirmation(submitted.id);
  }

  Future<void> _approveConfirmation(String confirmationId) async {
    final detail = ConfirmationDetails.fromJson(
      expectJsonObject(
        await _apiClient.get('/confirmations/$confirmationId'),
        context: '确认单详情接口',
      ),
    );
    final decision = expectJsonObject(
      await _apiClient.post(
        '/confirmations/$confirmationId/approve',
        idempotencyKey: _uuid.v4(),
        body: {'expected_version': detail.version},
      ),
      context: '确认执行接口',
    );
    if (decision['status'] != 'succeeded') {
      throw const ApiException(
        code: 'CONFIRMATION_FAILED',
        message: '操作未能生效，请刷新后重试',
      );
    }
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

  Future<Workout> startWorkout(
    CalendarEvent event, {
    PreWorkoutCheckInput? preCheck,
  }) async {
    final operationId = _uuid.v4();
    final json = expectJsonObject(
      await _apiClient.post(
        '/workouts',
        idempotencyKey: operationId,
        body: {
          'calendar_event_id': event.id,
          'plan_day_id': event.planDayId,
          'started_at': DateTime.now().toUtc().toIso8601String(),
          'pre_check': preCheck?.toJson(),
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

  Future<WorkoutSet> updateSet({
    required Workout workout,
    required WorkoutSet set,
    required double weightKg,
    required int reps,
  }) async {
    final json = expectJsonObject(
      await _apiClient.patch(
        '/workouts/${workout.id}/sets/${set.id}',
        body: {
          'weight_kg': weightKg,
          'reps': reps,
          'reason': '用户在移动端修改训练组',
          'expected_version': set.version,
        },
      ),
      context: '修改训练组接口',
    );
    return WorkoutSet.fromJson(json);
  }

  Future<void> deleteSet({required Workout workout, required WorkoutSet set}) =>
      _apiClient
          .delete(
            '/workouts/${workout.id}/sets/${set.id}',
            body: {'reason': '用户在移动端删除训练组', 'expected_version': set.version},
          )
          .then((_) {});

  Future<Workout> addExercise({
    required Workout workout,
    required String exerciseId,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/workouts/${workout.id}/exercises',
        idempotencyKey: _uuid.v4(),
        body: {
          'exercise_id': exerciseId,
          'target_sets': 3,
          'rep_min': 8,
          'rep_max': 12,
          'target_load_kg': null,
          'target_rir': 2,
          'rest_seconds': 90,
          'expected_workout_version': workout.version,
        },
      ),
      context: '临时添加训练动作接口',
    );
    return Workout.fromJson(json);
  }

  Future<Workout> replaceExercise({
    required Workout workout,
    required WorkoutExercise exercise,
    required String replacementExerciseId,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/workouts/${workout.id}/exercises/${exercise.id}/replace',
        body: {
          'replacement_exercise_id': replacementExerciseId,
          'reason': '用户在训练中替换动作',
          'expected_workout_version': workout.version,
        },
      ),
      context: '替换训练动作接口',
    );
    return Workout.fromJson(json);
  }

  Future<Workout> skipExercise({
    required Workout workout,
    required WorkoutExercise exercise,
  }) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/workouts/${workout.id}/exercises/${exercise.id}/skip',
        idempotencyKey: _uuid.v4(),
        body: {
          'reason': '用户在训练中跳过动作',
          'expected_workout_version': workout.version,
        },
      ),
      context: '跳过训练动作接口',
    );
    return Workout.fromJson(json);
  }

  Future<Workout> abandonWorkout(Workout workout) async {
    final json = expectJsonObject(
      await _apiClient.post(
        '/workouts/${workout.id}/abandon',
        idempotencyKey: _uuid.v4(),
        body: {
          'ended_at': DateTime.now().toUtc().toIso8601String(),
          'reason': '用户主动放弃本次训练',
          'expected_version': workout.version,
        },
      ),
      context: '放弃训练接口',
    );
    return Workout.fromJson(json);
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

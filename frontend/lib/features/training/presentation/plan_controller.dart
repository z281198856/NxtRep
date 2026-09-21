import 'package:flutter/foundation.dart';

import '../../../core/network/api_exception.dart';
import '../data/training_repository.dart';
import '../domain/training_models.dart';

class PlanController extends ChangeNotifier {
  PlanController(this._repository);

  final TrainingRepository _repository;

  ActiveTrainingPlan? activePlan;
  List<CalendarEvent> events = const [];
  List<TrainingTemplate> templates = const [];
  List<WorkoutHistoryItem> history = const [];
  bool loading = false;
  bool submitting = false;
  bool detailLoading = false;
  String? activatingTemplateId;
  String? errorMessage;

  Future<void> refresh() async {
    if (loading) return;
    loading = true;
    errorMessage = null;
    notifyListeners();
    try {
      final start = DateTime.now();
      final end = start.add(const Duration(days: 13));
      final values = await Future.wait<Object?>([
        _repository.getActivePlan(),
        _repository.getCalendar(start, end),
        _repository.getTemplates(),
        _repository.getWorkoutHistory(pageSize: 20),
      ]);
      activePlan = values[0] as ActiveTrainingPlan?;
      events = values[1] as List<CalendarEvent>;
      templates = values[2] as List<TrainingTemplate>;
      history = (values[3] as WorkoutHistoryPageData).items;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<bool> activateTemplate(TrainingTemplate template) async {
    if (submitting) return false;
    submitting = true;
    activatingTemplateId = template.id;
    errorMessage = null;
    notifyListeners();
    try {
      activePlan = await _repository.activateTemplate(template);
      final now = DateTime.now();
      events = await _repository.getCalendar(
        now,
        now.add(const Duration(days: 13)),
      );
      return true;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return false;
    } finally {
      submitting = false;
      activatingTemplateId = null;
      notifyListeners();
    }
  }

  Future<Workout?> loadWorkout(String workoutId) async {
    if (detailLoading) return null;
    detailLoading = true;
    errorMessage = null;
    notifyListeners();
    try {
      return await _repository.getWorkout(workoutId);
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return null;
    } finally {
      detailLoading = false;
      notifyListeners();
    }
  }

  String _messageFor(ApiException error) => switch (error.code) {
    'TRAINING_NOT_FOUND' => '没有找到适合当前条件的官方训练计划',
    'TRAINING_PLAN_INVALID' => '计划内容未通过校验，请选择其他计划',
    'TRAINING_VERSION_CONFLICT' ||
    'CONFIRMATION_CONFLICT' => '计划已在其他设备更新，请刷新后重试',
    _ => error.message,
  };
}

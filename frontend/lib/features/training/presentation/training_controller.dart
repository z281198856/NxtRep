import 'package:flutter/foundation.dart';

import '../../../core/network/api_exception.dart';
import '../data/training_repository.dart';
import '../domain/training_models.dart';

class TrainingController extends ChangeNotifier {
  TrainingController(this._repository);

  final TrainingRepository _repository;

  bool loading = false;
  bool submitting = false;
  String? errorMessage;
  List<CalendarEvent> events = const [];
  Workout? activeWorkout;

  Future<void> refresh() async {
    if (loading) return;
    loading = true;
    errorMessage = null;
    notifyListeners();
    try {
      final now = DateTime.now();
      final results = await Future.wait<Object?>([
        _repository.getCalendar(now, now),
        _repository.getActiveWorkout(),
      ]);
      events = results[0] as List<CalendarEvent>;
      activeWorkout = results[1] as Workout?;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<bool> start(CalendarEvent event) async {
    return _perform(() async {
      activeWorkout = await _repository.startWorkout(event);
    });
  }

  Future<bool> completeSet({
    required WorkoutExercise exercise,
    required double weightKg,
    required int reps,
  }) async {
    final workout = activeWorkout;
    if (workout == null) return false;
    return _perform(() async {
      await _repository.createSet(
        workout: workout,
        exercise: exercise,
        weightKg: weightKg,
        reps: reps,
      );
      activeWorkout = await _repository.getActiveWorkout();
    });
  }

  Future<bool> togglePause() async {
    final workout = activeWorkout;
    if (workout == null) return false;
    return _perform(() async {
      activeWorkout = workout.status == 'paused'
          ? await _repository.resumeWorkout(workout)
          : await _repository.pauseWorkout(workout);
    });
  }

  Future<WorkoutFinishSummary?> finish({
    int? overallDifficulty,
    int? fatigue,
  }) async {
    final workout = activeWorkout;
    if (workout == null || submitting) return null;

    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      final summary = await _repository.finishWorkout(
        workout,
        overallDifficulty: overallDifficulty,
        fatigue: fatigue,
      );
      activeWorkout = null;
      await refresh();
      return summary;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return null;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }

  Future<bool> _perform(Future<void> Function() action) async {
    if (submitting) return false;
    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      await action();
      return true;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return false;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }

  String _messageFor(ApiException error) => switch (error.code) {
    'WORKOUT_VERSION_CONFLICT' => '训练记录已在其他设备更新，已停止本次提交，请刷新后重试',
    'ACTIVE_WORKOUT_EXISTS' => '已有一场进行中的训练',
    'NETWORK_ERROR' => '暂时无法连接后端，训练离线队列将在后续版本启用',
    _ => error.message,
  };
}

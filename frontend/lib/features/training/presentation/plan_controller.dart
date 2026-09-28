import 'package:flutter/foundation.dart';

import '../../../core/media/image_upload.dart';
import '../../../core/network/api_exception.dart';
import '../../profile/data/profile_repository.dart';
import '../../profile/domain/profile_models.dart';
import '../data/training_repository.dart';
import '../domain/training_models.dart';

class PlanController extends ChangeNotifier {
  PlanController(
    this._repository, {
    this.imageUploader,
    this.profileRepository,
  });

  final TrainingRepository _repository;
  final ProfileDataSource? profileRepository;
  final Future<UploadedImage> Function(Uint8List)? imageUploader;

  ActiveTrainingPlan? activePlan;
  List<CalendarEvent> events = const [];
  List<TrainingTemplate> templates = const [];
  List<WorkoutHistoryItem> history = const [];
  bool loading = false;
  bool submitting = false;
  bool detailLoading = false;
  String? activatingTemplateId;
  String? errorMessage;
  String? recognizedImportText;
  UserProfile? recommendationProfile;
  TrainingPreferences? recommendationPreferences;

  List<TrainingTemplate> get recommendedTemplates {
    final preferences = recommendationPreferences;
    if (preferences != null) {
      final allowedEquipment = preferences.equipment.toSet();
      final compatible = templates.where((template) {
        return allowedEquipment.isEmpty ||
            template.equipment.isEmpty ||
            template.equipment.every(
              (gear) => gear == 'bodyweight' || allowedEquipment.contains(gear),
            );
      }).toList();
      final available = compatible;
      final goalMatches = available
          .where(
            (template) => template.goalTypes.contains(preferences.goalType),
          )
          .toList();
      final ranked = goalMatches.isEmpty ? available.toList() : goalMatches;
      final desiredDays = recommendationProfile?.weeklyTrainingDays ?? 3;
      final desiredMinutes = recommendationProfile?.sessionDurationMinutes;
      ranked.sort((left, right) {
        final dayComparison = (left.daysPerWeek - desiredDays).abs().compareTo(
          (right.daysPerWeek - desiredDays).abs(),
        );
        if (dayComparison != 0) return dayComparison;
        if (preferences.trainingMode == ProfileTrainingMode.gymEquipment) {
          final leftGym = left.equipment.any((gear) => gear != 'bodyweight');
          final rightGym = right.equipment.any((gear) => gear != 'bodyweight');
          if (leftGym != rightGym) return leftGym ? -1 : 1;
        }
        if (desiredMinutes != null) {
          final durationComparison = (left.durationMinutes - desiredMinutes)
              .abs()
              .compareTo((right.durationMinutes - desiredMinutes).abs());
          if (durationComparison != 0) return durationComparison;
        }
        return left.name.compareTo(right.name);
      });
      return ranked.take(8).toList();
    }

    final selected = <TrainingTemplate>[];
    for (final gear in ['bodyweight', 'dumbbell', 'barbell', 'cable']) {
      for (final goal in ['muscle_gain', 'fat_loss_retain', 'strength']) {
        final matches = templates.where(
          (item) =>
              item.daysPerWeek == 3 &&
              item.goalTypes.contains(goal) &&
              item.equipment.contains(gear) &&
              item.equipment.every(
                (value) => value == gear || value == 'bodyweight',
              ),
        );
        if (matches.isNotEmpty) selected.add(matches.first);
      }
    }
    return selected.isEmpty ? templates.take(12).toList() : selected;
  }

  String get recommendationDescription {
    final preferences = recommendationPreferences;
    if (preferences == null) {
      return '增肌塑形、减脂保肌与力量基础；点开可预览每一天的动作。';
    }
    final goal = switch (preferences.goalType) {
      'muscle_gain' => '增肌塑形',
      'fat_loss_retain' => '减脂保肌',
      'strength' => '提升力量',
      _ => '你的训练目标',
    };
    final days = recommendationProfile?.weeklyTrainingDays;
    return '根据$goal、${preferences.trainingMode == ProfileTrainingMode.bodyweight ? '徒手' : '器械'}条件${days == null ? '' : '和每周 $days 天'}排序；点开可预览每天的动作。';
  }

  Future<TrainingTemplateDetail> getTemplateDetail(String id) =>
      _repository.getTemplateDetail(id);

  Future<void> refresh() async {
    if (loading) return;
    loading = true;
    errorMessage = null;
    notifyListeners();
    final recommendationFuture = _refreshRecommendationContext();
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
      await recommendationFuture;
      loading = false;
      notifyListeners();
    }
  }

  Future<void> _refreshRecommendationContext() async {
    final source = profileRepository;
    if (source == null) return;
    try {
      final values = await Future.wait<Object>([
        source.getProfile(),
        source.getTrainingPreferences(),
      ]);
      recommendationProfile = values[0] as UserProfile;
      recommendationPreferences = values[1] as TrainingPreferences;
    } on Exception {
      // Plan browsing remains available if profile services are unavailable.
      recommendationProfile = null;
      recommendationPreferences = null;
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

  Future<PlanDraft?> generatePlan({
    required String goalType,
    required int daysPerWeek,
    required String equipment,
    String? name,
  }) => _loadDraft(
    () => _repository.generatePlanDraft(
      goalType: goalType,
      daysPerWeek: daysPerWeek,
      equipment: equipment,
      name: name,
    ),
  );

  Future<PlanDraft?> importPlanText(String text, {String? name}) =>
      _loadDraft(() => _repository.parsePlanText(text: text, name: name));

  Future<PlanDraft?> importPlanImage(Uint8List source, {String? name}) =>
      _loadDraft(() async {
        final uploader = imageUploader;
        if (uploader == null) {
          throw const ApiException(
            code: 'IMAGE_UPLOAD_UNAVAILABLE',
            message: '当前无法上传训练计划图片',
          );
        }
        final uploaded = await uploader(source);
        try {
          final draft = await _repository.parsePlanImage(
            imageAssetId: uploaded.assetId,
            name: name,
          );
          recognizedImportText = draft.recognizedText;
          return draft;
        } on ApiException catch (error) {
          final details = error.details;
          if (details is Map && details['recognized_text'] is String) {
            recognizedImportText = details['recognized_text'] as String;
          }
          rethrow;
        }
      });

  Future<PlanDraft?> _loadDraft(Future<PlanDraft> Function() load) async {
    if (submitting) return null;
    submitting = true;
    errorMessage = null;
    recognizedImportText = null;
    notifyListeners();
    try {
      return await load();
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return null;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }

  Future<bool> activateDraft(PlanDraft draft) async {
    if (submitting) return false;
    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      activePlan = await _repository.activateDraft(draft);
      await _refreshCalendar();
      return true;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return false;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }

  Future<bool> createCalendarEvent({
    required DateTime date,
    required String title,
    required int estimatedMinutes,
  }) => _calendarMutation(
    () => _repository.createCalendarEvent(
      date: date,
      title: title,
      estimatedMinutes: estimatedMinutes,
    ),
  );

  Future<bool> rescheduleEvent({
    required CalendarEvent event,
    required String strategy,
    DateTime? targetDate,
  }) => _calendarMutation(
    () => _repository.rescheduleEvent(
      event: event,
      strategy: strategy,
      targetDate: targetDate,
      reason: '用户在移动端调整训练日历',
    ),
  );

  Future<bool> compressEvent(
    CalendarEvent event, {
    required int targetMinutes,
  }) => _calendarMutation(
    () => _repository.compressEvent(
      event: event,
      targetMinutes: targetMinutes,
      reason: '用户可用训练时间发生变化',
    ),
  );

  Future<bool> _calendarMutation(Future<Object?> Function() action) async {
    if (submitting) return false;
    submitting = true;
    errorMessage = null;
    notifyListeners();
    try {
      await action();
      await _refreshCalendar();
      return true;
    } on ApiException catch (error) {
      errorMessage = _messageFor(error);
      return false;
    } finally {
      submitting = false;
      notifyListeners();
    }
  }

  Future<void> _refreshCalendar() async {
    final now = DateTime.now();
    events = await _repository.getCalendar(
      now,
      now.add(const Duration(days: 13)),
    );
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

double _decimalToDouble(Object? value) => switch (value) {
  num number => number.toDouble(),
  String text => double.parse(text),
  _ => 0,
};

class ActiveTrainingPlan {
  const ActiveTrainingPlan({
    required this.id,
    required this.planId,
    required this.name,
    required this.version,
    required this.weeklyFrequency,
    required this.days,
  });

  factory ActiveTrainingPlan.fromJson(Map<String, dynamic> json) =>
      ActiveTrainingPlan(
        id: json['id'] as String,
        planId: json['plan_id'] as String,
        name: json['name'] as String,
        version: json['version'] as int,
        weeklyFrequency: json['weekly_frequency'] as int,
        days: (json['days'] as List<dynamic>? ?? const [])
            .map(
              (item) => TrainingPlanDay.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
      );

  final String id;
  final String planId;
  final String name;
  final int version;
  final int weeklyFrequency;
  final List<TrainingPlanDay> days;
}

class TrainingPlanDay {
  const TrainingPlanDay({
    required this.id,
    required this.dayIndex,
    required this.name,
    required this.estimatedMinutes,
    required this.exercises,
  });

  factory TrainingPlanDay.fromJson(Map<String, dynamic> json) =>
      TrainingPlanDay(
        id: json['id'] as String? ?? '',
        dayIndex: json['day_index'] as int,
        name: json['name'] as String,
        estimatedMinutes: json['estimated_minutes'] as int,
        exercises: (json['exercises'] as List<dynamic>? ?? const [])
            .map((item) => Map<String, dynamic>.from(item as Map))
            .toList(growable: false),
      );

  final String id;
  final int dayIndex;
  final String name;
  final int estimatedMinutes;
  final List<Map<String, dynamic>> exercises;
}

class TrainingTemplate {
  const TrainingTemplate({
    required this.id,
    required this.name,
    required this.goalTypes,
    required this.daysPerWeek,
    required this.durationMinutes,
    this.equipment = const [],
  });

  factory TrainingTemplate.fromJson(Map<String, dynamic> json) =>
      TrainingTemplate(
        id: json['id'] as String,
        name: json['name'] as String,
        goalTypes: (json['goal_types'] as List<dynamic>).cast<String>().toList(
          growable: false,
        ),
        daysPerWeek: json['days_per_week'] as int,
        durationMinutes: json['duration_minutes'] as int,
        equipment: (json['equipment'] as List<dynamic>? ?? const [])
            .cast<String>(),
      );

  final String id;
  final String name;
  final List<String> goalTypes;
  final int daysPerWeek;
  final int durationMinutes;
  final List<String> equipment;
}

class TrainingTemplateDetail {
  const TrainingTemplateDetail({required this.template, required this.days});

  factory TrainingTemplateDetail.fromJson(Map<String, dynamic> json) =>
      TrainingTemplateDetail(
        template: TrainingTemplate.fromJson(json),
        days: (json['days'] as List<dynamic>? ?? const [])
            .map(
              (item) => TrainingPlanDay.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
      );

  final TrainingTemplate template;
  final List<TrainingPlanDay> days;
}

class PlanDraft {
  const PlanDraft({
    required this.id,
    required this.name,
    required this.status,
    required this.version,
    required this.weeklyFrequency,
    required this.days,
    this.recognizedText,
  });

  factory PlanDraft.fromJson(Map<String, dynamic> json) => PlanDraft(
    id: json['id'] as String,
    name: json['name'] as String,
    status: json['status'] as String,
    version: json['version'] as int,
    weeklyFrequency: json['weekly_frequency'] as int,
    recognizedText: json['recognized_text'] as String?,
    days: (json['days'] as List<dynamic>? ?? const [])
        .map((item) => TrainingPlanDay.fromJson(item as Map<String, dynamic>))
        .toList(growable: false),
  );

  final String id;
  final String name;
  final String status;
  final int version;
  final int weeklyFrequency;
  final List<TrainingPlanDay> days;
  final String? recognizedText;
}

class PlanValidation {
  const PlanValidation({
    required this.valid,
    required this.estimatedWeeklyMinutes,
    required this.errors,
    required this.warnings,
  });

  factory PlanValidation.fromJson(Map<String, dynamic> json) => PlanValidation(
    valid: json['valid'] as bool,
    estimatedWeeklyMinutes: json['estimated_weekly_minutes'] as int,
    errors: (json['errors'] as List<dynamic>? ?? const [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList(growable: false),
    warnings: (json['warnings'] as List<dynamic>? ?? const [])
        .map((item) => Map<String, dynamic>.from(item as Map))
        .toList(growable: false),
  );

  final bool valid;
  final int estimatedWeeklyMinutes;
  final List<Map<String, dynamic>> errors;
  final List<Map<String, dynamic>> warnings;
}

class PlanConfirmation {
  const PlanConfirmation({
    required this.id,
    required this.status,
    required this.impact,
  });

  factory PlanConfirmation.fromSubmitJson(Map<String, dynamic> json) =>
      PlanConfirmation(
        id: json['confirmation_id'] as String,
        status: json['status'] as String,
        impact: json['impact'] as String,
      );

  final String id;
  final String status;
  final String impact;
}

class ConfirmationDetails {
  const ConfirmationDetails({
    required this.id,
    required this.status,
    required this.version,
  });

  factory ConfirmationDetails.fromJson(Map<String, dynamic> json) =>
      ConfirmationDetails(
        id: json['id'] as String,
        status: json['status'] as String,
        version: json['version'] as int,
      );

  final String id;
  final String status;
  final int version;
}

class CalendarEvent {
  const CalendarEvent({
    required this.id,
    required this.scheduledDate,
    required this.status,
    required this.title,
    required this.estimatedMinutes,
    this.planDayId,
    this.actualWorkoutId,
  });

  factory CalendarEvent.fromJson(Map<String, dynamic> json) => CalendarEvent(
    id: json['id'] as String,
    scheduledDate: DateTime.parse(json['scheduled_date'] as String),
    status: json['status'] as String,
    title: json['title'] as String,
    estimatedMinutes: json['estimated_minutes'] as int,
    planDayId: json['plan_day_id'] as String?,
    actualWorkoutId: json['actual_workout_id'] as String?,
  );

  final String id;
  final DateTime scheduledDate;
  final String status;
  final String? planDayId;
  final String title;
  final int estimatedMinutes;
  final String? actualWorkoutId;
}

class PreWorkoutCheckInput {
  const PreWorkoutCheckInput({
    required this.sleepQuality,
    required this.energy,
    required this.availableMinutes,
  });

  final int sleepQuality;
  final int energy;
  final int availableMinutes;

  Map<String, Object> toJson() => {
    'sleep_quality': sleepQuality,
    'energy': energy,
    'pain': const <Object>[],
    'available_minutes': availableMinutes,
  };
}

class CalendarAdjustmentDraft {
  const CalendarAdjustmentDraft({
    required this.id,
    required this.strategy,
    required this.durationChangeMinutes,
    required this.volumeChangePercent,
    required this.warnings,
    required this.version,
  });

  factory CalendarAdjustmentDraft.fromJson(Map<String, dynamic> json) =>
      CalendarAdjustmentDraft(
        id: json['id'] as String,
        strategy: json['strategy'] as String,
        durationChangeMinutes: json['duration_change_minutes'] as int? ?? 0,
        volumeChangePercent: _decimalToDouble(json['volume_change_percent']),
        warnings: (json['warnings'] as List<dynamic>? ?? const [])
            .whereType<String>()
            .toList(growable: false),
        version: json['version'] as int,
      );

  final String id;
  final String strategy;
  final int durationChangeMinutes;
  final double volumeChangePercent;
  final List<String> warnings;
  final int version;
}

class WorkoutSet {
  const WorkoutSet({
    required this.id,
    required this.setIndex,
    required this.weightKg,
    required this.reps,
    required this.completedAt,
    required this.version,
  });

  factory WorkoutSet.fromJson(Map<String, dynamic> json) => WorkoutSet(
    id: json['id'] as String,
    setIndex: json['set_index'] as int,
    weightKg: _decimalToDouble(json['weight_kg']),
    reps: json['reps'] as int,
    completedAt: DateTime.parse(json['completed_at'] as String),
    version: json['version'] as int,
  );

  final String id;
  final int setIndex;
  final double weightKg;
  final int reps;
  final DateTime completedAt;
  final int version;
}

class WorkoutExercise {
  const WorkoutExercise({
    required this.id,
    required this.name,
    required this.target,
    required this.skipped,
    required this.sets,
    this.exerciseId,
  });

  factory WorkoutExercise.fromJson(Map<String, dynamic> json) =>
      WorkoutExercise(
        id: json['id'] as String,
        exerciseId: json['exercise_id'] as String?,
        name: json['name_snapshot'] as String,
        target: Map<String, dynamic>.from(json['target_snapshot'] as Map),
        skipped: json['skipped'] as bool? ?? false,
        sets: (json['sets'] as List<dynamic>)
            .map((item) => WorkoutSet.fromJson(item as Map<String, dynamic>))
            .toList(growable: false),
      );

  final String id;
  final String? exerciseId;
  final String name;
  final Map<String, dynamic> target;
  final bool skipped;
  final List<WorkoutSet> sets;

  int get targetSets => target['target_sets'] as int? ?? 3;
  int get repMin => target['rep_min'] as int? ?? 8;
  int get repMax => target['rep_max'] as int? ?? 12;
  int get restSeconds => target['rest_seconds'] as int? ?? 0;
  double get targetLoadKg => _decimalToDouble(target['target_load_kg']);
  bool get completed => sets.length >= targetSets;
}

class WorkoutRestTimer {
  const WorkoutRestTimer({required this.durationSeconds, required this.endsAt});

  factory WorkoutRestTimer.fromJson(Map<String, dynamic> json) =>
      WorkoutRestTimer(
        durationSeconds: json['duration_seconds'] as int,
        endsAt: DateTime.parse(json['ends_at'] as String),
      );

  final int durationSeconds;
  final DateTime endsAt;

  int remainingAt(DateTime now) =>
      endsAt.difference(now.toUtc()).inSeconds.clamp(0, durationSeconds);
}

class Workout {
  const Workout({
    required this.id,
    required this.status,
    required this.startedAt,
    required this.elapsedSeconds,
    required this.version,
    required this.exercises,
    this.restTimer,
    this.pausedAt,
    this.totalPausedSeconds = 0,
  });

  factory Workout.fromJson(Map<String, dynamic> json) => Workout(
    id: json['id'] as String,
    status: json['status'] as String,
    startedAt: DateTime.parse(json['started_at'] as String),
    pausedAt: json['paused_at'] == null
        ? null
        : DateTime.parse(json['paused_at'] as String),
    totalPausedSeconds: json['total_paused_seconds'] as int? ?? 0,
    elapsedSeconds: json['elapsed_seconds'] as int? ?? 0,
    version: json['version'] as int,
    restTimer: json['rest_timer'] == null
        ? null
        : WorkoutRestTimer.fromJson(json['rest_timer'] as Map<String, dynamic>),
    exercises: (json['exercises'] as List<dynamic>)
        .map((item) => WorkoutExercise.fromJson(item as Map<String, dynamic>))
        .toList(growable: false),
  );

  final String id;
  final String status;
  final DateTime startedAt;
  final DateTime? pausedAt;
  final int totalPausedSeconds;
  final int elapsedSeconds;
  final WorkoutRestTimer? restTimer;
  final int version;
  final List<WorkoutExercise> exercises;

  int get completedSetCount =>
      exercises.fold(0, (total, exercise) => total + exercise.sets.length);

  int elapsedAt(DateTime now) {
    if (status == 'paused') return elapsedSeconds;
    return (now.toUtc().difference(startedAt.toUtc()).inSeconds -
            totalPausedSeconds)
        .clamp(0, 1 << 31);
  }
}

class WorkoutHistoryItem {
  const WorkoutHistoryItem({
    required this.id,
    required this.date,
    required this.status,
    required this.durationSeconds,
    required this.completedSets,
    required this.totalVolumeKg,
    required this.prCount,
  });

  factory WorkoutHistoryItem.fromJson(Map<String, dynamic> json) =>
      WorkoutHistoryItem(
        id: json['id'] as String,
        date: DateTime.parse(json['date'] as String),
        status: json['status'] as String,
        durationSeconds: json['duration_seconds'] as int?,
        completedSets: json['completed_sets'] as int,
        totalVolumeKg: _decimalToDouble(json['total_volume_kg']),
        prCount: json['pr_count'] as int,
      );

  final String id;
  final DateTime date;
  final String status;
  final int? durationSeconds;
  final int completedSets;
  final double totalVolumeKg;
  final int prCount;
}

class WorkoutHistoryPageData {
  const WorkoutHistoryPageData({
    required this.items,
    required this.total,
    required this.hasMore,
  });

  factory WorkoutHistoryPageData.fromJson(Map<String, dynamic> json) =>
      WorkoutHistoryPageData(
        items: (json['list'] as List<dynamic>)
            .map(
              (item) =>
                  WorkoutHistoryItem.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
        total: json['total'] as int,
        hasMore: json['has_more'] as bool,
      );

  final List<WorkoutHistoryItem> items;
  final int total;
  final bool hasMore;
}

class WorkoutFinishSummary {
  const WorkoutFinishSummary({
    required this.workoutId,
    required this.durationSeconds,
    required this.completedSets,
    required this.totalVolumeKg,
    required this.prCount,
  });

  factory WorkoutFinishSummary.fromJson(Map<String, dynamic> json) =>
      WorkoutFinishSummary(
        workoutId: json['workout_id'] as String,
        durationSeconds: json['duration_seconds'] as int,
        completedSets: json['completed_sets'] as int,
        totalVolumeKg: _decimalToDouble(json['total_volume_kg']),
        prCount: (json['prs'] as List<dynamic>).length,
      );

  final String workoutId;
  final int durationSeconds;
  final int completedSets;
  final double totalVolumeKg;
  final int prCount;
}

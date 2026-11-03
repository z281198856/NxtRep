import '../../../core/settings/app_preferences.dart';

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/offline/form_draft.dart';

import '../../exercises/data/exercise_repository.dart';
import '../../exercises/domain/exercise_models.dart';
import '../domain/training_models.dart';
import 'training_controller.dart';

class WorkoutPage extends StatefulWidget {
  const WorkoutPage({
    super.key,
    required this.controller,
    required this.exerciseRepository,
  });

  final TrainingController controller;
  final ExerciseRepository exerciseRepository;

  @override
  State<WorkoutPage> createState() => _WorkoutPageState();
}

class _WorkoutPageState extends State<WorkoutPage> {
  Timer? _ticker;
  final _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _recordSet(WorkoutExercise exercise) async {
    final input = await showModalBottomSheet<_SetInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _SetEntrySheet(exercise: exercise),
    );
    if (input == null) return;
    final saved = await widget.controller.completeSet(
      exercise: exercise,
      weightKg: input.weightKg,
      reps: input.reps,
    );
    if (mounted && saved) {
      await clearSubmittedDraft(context, 'set:${exercise.id}:new');
    }
  }

  Future<void> _editSet(WorkoutExercise exercise, WorkoutSet set) async {
    final input = await showModalBottomSheet<_SetInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _SetEntrySheet(exercise: exercise, editingSet: set),
    );
    if (input == null) return;
    final saved = await widget.controller.updateSet(
      set: set,
      weightKg: input.weightKg,
      reps: input.reps,
    );
    if (mounted && saved) {
      await clearSubmittedDraft(context, 'set:${exercise.id}:${set.id}');
    }
  }

  Future<void> _deleteSet(WorkoutSet set) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这一组？'),
        content: const Text('删除后训练容量和完成组数会同步更新。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed == true) await widget.controller.deleteSet(set);
  }

  Future<ExerciseListItem?> _chooseExercise({String title = '选择动作'}) {
    return showModalBottomSheet<ExerciseListItem>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _ExercisePickerSheet(
        title: title,
        repository: widget.exerciseRepository,
      ),
    );
  }

  Future<void> _addExercise() async {
    final workout = widget.controller.activeWorkout;
    if (workout == null) return;
    final selected = await _chooseExercise(
      title: workout.isPlanBased
          ? '临时添加动作'
          : workout.exercises.isEmpty
          ? '添加第一个动作'
          : '下一个动作',
    );
    if (selected == null) return;
    if (await widget.controller.addExercise(selected.id) && mounted) {
      await WidgetsBinding.instance.endOfFrame;
      if (mounted && _scrollController.hasClients) {
        await _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    }
  }

  Future<void> _adjustTarget(
    WorkoutExercise exercise, {
    bool rest = false,
  }) async {
    final value = await showModalBottomSheet<int>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _NumberSettingSheet(
        title: rest ? '组间休息' : '调整目标组数',
        label: rest ? '休息时长（秒）' : '目标组数',
        initialValue: rest ? exercise.restSeconds : exercise.targetSets,
        minimum: rest ? 0 : exercise.sets.length.clamp(1, 20),
        maximum: rest ? 1800 : 20,
        presets: rest ? const [30, 60, 90, 120, 180] : const [3, 4, 5, 6],
        helper: rest
            ? '用于这个动作的组间休息；当前倒计时从最近一组完成时计算。0 秒表示关闭。'
            : '只调整本次训练，已完成的组会保留。',
      ),
    );
    if (value == null) return;
    if (rest && value == exercise.restSeconds ||
        !rest && value == exercise.targetSets) {
      return;
    }
    await widget.controller.updateExerciseTarget(
      exercise,
      targetSets: rest ? null : value,
      restSeconds: rest ? value : null,
    );
  }

  Future<void> _replaceExercise(WorkoutExercise exercise) async {
    final selected = await _chooseExercise(title: '替换 ${exercise.name}');
    if (selected != null) {
      await widget.controller.replaceExercise(exercise, selected.id);
    }
  }

  Future<void> _skipExercise(WorkoutExercise exercise) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('跳过 ${exercise.name}？'),
        content: const Text('这次训练会保留跳过记录，之后仍可查看。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认跳过'),
          ),
        ],
      ),
    );
    if (confirmed == true) await widget.controller.skipExercise(exercise);
  }

  Future<void> _abandon() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('放弃本次训练？'),
        content: const Text('已完成的训练组会保留，本次训练将标记为已放弃。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('继续训练'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认放弃'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    if (await widget.controller.abandon() && mounted) Navigator.pop(context);
  }

  Future<void> _finish() async {
    final feedback = await showModalBottomSheet<_FinishInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _FinishWorkoutSheet(),
    );
    if (feedback == null) return;

    final summary = await widget.controller.finish(
      overallDifficulty: feedback.difficulty,
      fatigue: feedback.fatigue,
    );
    if (summary == null || !mounted) return;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('训练完成'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('完成 ${summary.completedSets} 组'),
            Text(
              '训练容量 ${AppPreferencesScope.unitsOf(context).formatWeight(summary.totalVolumeKg)}',
            ),
            Text('用时 ${_formatDuration(summary.durationSeconds)}'),
            if (summary.prCount > 0) Text('刷新 ${summary.prCount} 项个人纪录'),
          ],
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('完成'),
          ),
        ],
      ),
    );
    if (mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        final workout = widget.controller.activeWorkout;
        if (workout == null) {
          return const Scaffold(body: Center(child: Text('没有进行中的训练')));
        }

        final paused = workout.status == 'paused';
        final addLabel = workout.isPlanBased
            ? '临时添加动作'
            : workout.exercises.isEmpty
            ? '添加第一个动作'
            : '下一个动作';
        final restExercise =
            workout.exercises
                .where(
                  (item) => item.id == workout.restTimer?.workoutExerciseId,
                )
                .firstOrNull ??
            workout.exercises
                .where((item) => !item.completed && !item.skipped)
                .firstOrNull ??
            workout.exercises.lastOrNull;
        return Scaffold(
          appBar: AppBar(
            title: Text(workout.isPlanBased ? '计划训练' : '自主训练'),
            bottom: PreferredSize(
              preferredSize: const Size.fromHeight(78),
              child: _WorkoutTimers(
                workout: workout,
                restExercise: restExercise,
                onAdjustRest:
                    restExercise == null ||
                        restExercise.skipped ||
                        paused ||
                        widget.controller.submitting
                    ? null
                    : () => _adjustTarget(restExercise, rest: true),
              ),
            ),
            actions: [
              IconButton(
                tooltip: paused ? '继续训练' : '暂停训练',
                onPressed: widget.controller.submitting
                    ? null
                    : widget.controller.togglePause,
                icon: Icon(
                  paused
                      ? Icons.play_arrow_rounded
                      : Icons.pause_circle_outline_rounded,
                ),
              ),
              TextButton(
                onPressed: widget.controller.submitting ? null : _finish,
                child: const Text('结束'),
              ),
              PopupMenuButton<String>(
                tooltip: '更多训练操作',
                onSelected: (value) {
                  if (value == 'add') _addExercise();
                  if (value == 'abandon') _abandon();
                },
                enabled: !widget.controller.submitting && !paused,
                itemBuilder: (_) => [
                  PopupMenuItem(value: 'add', child: Text(addLabel)),
                  const PopupMenuItem(value: 'abandon', child: Text('放弃本次训练')),
                ],
              ),
            ],
          ),
          body: ListView(
            controller: _scrollController,
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
            children: [
              if (paused) ...[
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(16),
                    child: Row(
                      children: [
                        Icon(Icons.pause_rounded),
                        SizedBox(width: 12),
                        Expanded(child: Text('训练已暂停，计时和组数记录暂时停止')),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              if (widget.controller.errorMessage case final message?) ...[
                Card(
                  color: Theme.of(context).colorScheme.errorContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Text(message),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              if (workout.exercises.isEmpty)
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Text('选择今天要练的第一个动作，练完后可以继续添加。'),
                  ),
                )
              else
                ...workout.exercises.map(
                  (exercise) => _ExerciseCard(
                    exercise: exercise,
                    submitting: widget.controller.submitting || paused,
                    onRecord: () => _recordSet(exercise),
                    onEditSet: (set) => _editSet(exercise, set),
                    onDeleteSet: _deleteSet,
                    onReplace: () => _replaceExercise(exercise),
                    onSkip: () => _skipExercise(exercise),
                    onAdjustSets: () => _adjustTarget(exercise),
                    onAdjustRest: () => _adjustTarget(exercise, rest: true),
                  ),
                ),
              const SizedBox(height: 4),
              OutlinedButton.icon(
                onPressed: widget.controller.submitting || paused
                    ? null
                    : _addExercise,
                icon: const Icon(Icons.add_rounded),
                label: Text(addLabel),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _WorkoutTimers extends StatelessWidget {
  const _WorkoutTimers({
    required this.workout,
    required this.restExercise,
    required this.onAdjustRest,
  });

  final Workout workout;
  final WorkoutExercise? restExercise;
  final VoidCallback? onAdjustRest;

  @override
  Widget build(BuildContext context) {
    final now = workout.status == 'paused'
        ? workout.pausedAt ?? DateTime.now()
        : DateTime.now();
    final remaining = workout.restTimer?.remainingAt(now) ?? 0;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('总用时'),
                Text(
                  _formatDuration(workout.elapsedAt(DateTime.now())),
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
              ],
            ),
          ),
          Expanded(
            child: TextButton.icon(
              onPressed: onAdjustRest,
              icon: const Icon(Icons.timer_outlined),
              label: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    workout.restTimer != null
                        ? remaining > 0
                              ? '组间休息'
                              : '休息结束'
                        : '休息时长',
                  ),
                  Text(
                    workout.restTimer != null
                        ? _formatDuration(remaining)
                        : _formatDuration(restExercise?.restSeconds ?? 90),
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ExerciseCard extends StatelessWidget {
  const _ExerciseCard({
    required this.exercise,
    required this.submitting,
    required this.onRecord,
    required this.onEditSet,
    required this.onDeleteSet,
    required this.onReplace,
    required this.onSkip,
    required this.onAdjustSets,
    required this.onAdjustRest,
  });

  final WorkoutExercise exercise;
  final bool submitting;
  final VoidCallback onRecord;
  final ValueChanged<WorkoutSet> onEditSet;
  final ValueChanged<WorkoutSet> onDeleteSet;
  final VoidCallback onReplace;
  final VoidCallback onSkip;
  final VoidCallback onAdjustSets;
  final VoidCallback onAdjustRest;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    exercise.name,
                    style: Theme.of(context).textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                TextButton.icon(
                  onPressed: submitting || exercise.skipped
                      ? null
                      : onAdjustSets,
                  icon: const Icon(Icons.edit_outlined, size: 16),
                  label: Text(
                    '${exercise.sets.length}/${exercise.targetSets} 组',
                  ),
                ),
                PopupMenuButton<String>(
                  tooltip: '动作操作',
                  enabled: !submitting && !exercise.skipped,
                  onSelected: (value) {
                    if (value == 'replace') onReplace();
                    if (value == 'skip') onSkip();
                  },
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 'replace', child: Text('替换动作')),
                    PopupMenuItem(value: 'skip', child: Text('跳过动作')),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 4),
            Row(
              children: [
                Text('${exercise.repMin}–${exercise.repMax} 次'),
                const Spacer(),
                TextButton(
                  onPressed: submitting || exercise.skipped
                      ? null
                      : onAdjustRest,
                  child: Text('休息 ${exercise.restSeconds} 秒'),
                ),
              ],
            ),
            if (exercise.sets.isNotEmpty) ...[
              const Divider(height: 24),
              for (final set in exercise.sets)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Row(
                    children: [
                      SizedBox(width: 40, child: Text('${set.setIndex}')),
                      Expanded(
                        child: Text(
                          AppPreferencesScope.unitsOf(context)
                              .formatWeight(set.weightKg),
                        ),
                      ),
                      Text('${set.reps} 次'),
                      if (set.id.startsWith('local-'))
                        const Padding(
                          padding: EdgeInsets.only(left: 6),
                          child: Text('待同步', style: TextStyle(fontSize: 11)),
                        ),
                      const SizedBox(width: 8),
                      PopupMenuButton<String>(
                        padding: EdgeInsets.zero,
                        tooltip: '训练组操作',
                        enabled: !submitting && !set.id.startsWith('local-'),
                        onSelected: (value) {
                          if (value == 'edit') onEditSet(set);
                          if (value == 'delete') onDeleteSet(set);
                        },
                        itemBuilder: (_) => const [
                          PopupMenuItem(value: 'edit', child: Text('修改')),
                          PopupMenuItem(value: 'delete', child: Text('删除')),
                        ],
                        icon: const Icon(Icons.more_horiz_rounded, size: 20),
                      ),
                    ],
                  ),
                ),
            ],
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: submitting || exercise.completed || exercise.skipped
                  ? null
                  : onRecord,
              icon: const Icon(Icons.check_rounded),
              label: Text(exercise.completed ? '已完成' : '完成下一组'),
            ),
          ],
        ),
      ),
    );
  }
}

class _NumberSettingSheet extends StatefulWidget {
  const _NumberSettingSheet({
    required this.title,
    required this.label,
    required this.initialValue,
    required this.minimum,
    required this.maximum,
    required this.presets,
    required this.helper,
  });

  final String title;
  final String label;
  final int initialValue;
  final int minimum;
  final int maximum;
  final List<int> presets;
  final String helper;

  @override
  State<_NumberSettingSheet> createState() => _NumberSettingSheetState();
}

class _NumberSettingSheetState extends State<_NumberSettingSheet> {
  late final _value = TextEditingController(text: '${widget.initialValue}');
  final _form = GlobalKey<FormState>();

  @override
  void dispose() {
    _value.dispose();
    super.dispose();
  }

  void _save() {
    if (_form.currentState!.validate()) {
      Navigator.pop(context, int.parse(_value.text));
    }
  }

  @override
  Widget build(BuildContext context) => SafeArea(
    top: false,
    child: SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(
        20,
        20,
        20,
        MediaQuery.viewInsetsOf(context).bottom + 20,
      ),
      child: Form(
        key: _form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(widget.title, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            TextFormField(
              controller: _value,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              decoration: InputDecoration(labelText: widget.label),
              validator: (value) {
                final number = int.tryParse(value ?? '');
                return number == null ||
                        number < widget.minimum ||
                        number > widget.maximum
                    ? '请输入 ${widget.minimum}–${widget.maximum}'
                    : null;
              },
              onFieldSubmitted: (_) => _save(),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              children: [
                for (final preset in widget.presets.where(
                  (n) => n >= widget.minimum,
                ))
                  ActionChip(
                    label: Text('$preset'),
                    onPressed: () => _value.text = '$preset',
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Text(widget.helper),
            const SizedBox(height: 18),
            FilledButton(onPressed: _save, child: const Text('保存')),
          ],
        ),
      ),
    ),
  );
}

class _FinishInput {
  const _FinishInput({required this.difficulty, required this.fatigue});

  final int difficulty;
  final int fatigue;
}

class _FinishWorkoutSheet extends StatefulWidget {
  const _FinishWorkoutSheet();

  @override
  State<_FinishWorkoutSheet> createState() => _FinishWorkoutSheetState();
}

class _FinishWorkoutSheetState extends State<_FinishWorkoutSheet> {
  int _difficulty = 3;
  int _fatigue = 3;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          20,
          20,
          20,
          MediaQuery.viewInsetsOf(context).bottom + 20,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('完成本次训练', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 6),
            Text(
              '简单记录感受，帮助之后调整计划强度。',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 20),
            _RatingRow(
              label: '总体难度',
              value: _difficulty,
              lowLabel: '轻松',
              highLabel: '很难',
              onChanged: (value) => setState(() => _difficulty = value),
            ),
            const SizedBox(height: 18),
            _RatingRow(
              label: '当前疲劳',
              value: _fatigue,
              lowLabel: '状态好',
              highLabel: '很疲劳',
              onChanged: (value) => setState(() => _fatigue = value),
            ),
            const SizedBox(height: 22),
            FilledButton(
              onPressed: () => Navigator.pop(
                context,
                _FinishInput(difficulty: _difficulty, fatigue: _fatigue),
              ),
              child: const Text('保存并完成训练'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('继续训练'),
            ),
          ],
        ),
      ),
    );
  }
}

class _RatingRow extends StatelessWidget {
  const _RatingRow({
    required this.label,
    required this.value,
    required this.lowLabel,
    required this.highLabel,
    required this.onChanged,
  });

  final String label;
  final int value;
  final String lowLabel;
  final String highLabel;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            Text(
              value == 1
                  ? lowLabel
                  : value == 5
                  ? highLabel
                  : '$value / 5',
            ),
          ],
        ),
        const SizedBox(height: 9),
        Row(
          children: [
            for (var rating = 1; rating <= 5; rating++) ...[
              Expanded(
                child: ChoiceChip(
                  label: Text('$rating'),
                  selected: value == rating,
                  onSelected: (_) => onChanged(rating),
                ),
              ),
              if (rating < 5) const SizedBox(width: 7),
            ],
          ],
        ),
      ],
    );
  }
}

class _SetInput {
  const _SetInput({required this.weightKg, required this.reps});

  final double weightKg;
  final int reps;
}

class _SetEntrySheet extends StatefulWidget {
  const _SetEntrySheet({required this.exercise, this.editingSet});

  final WorkoutExercise exercise;
  final WorkoutSet? editingSet;

  @override
  State<_SetEntrySheet> createState() => _SetEntrySheetState();
}

class _SetEntrySheetState extends State<_SetEntrySheet> {
  late final TextEditingController _weight;
  late final MeasurementUnits _units;
  late final double _initialWeight;
  late final TextEditingController _reps;
  final _formKey = GlobalKey<FormState>();
  late final FormDraft _formDraft;

  @override
  void initState() {
    super.initState();
    final last = widget.editingSet ?? widget.exercise.sets.lastOrNull;
    _initialWeight = last?.weightKg ?? widget.exercise.targetLoadKg;
    _units = AppPreferencesScope.readUnits(context);
    _weight = TextEditingController(text: _units.weightInput(_initialWeight));
    _reps = TextEditingController(
      text: (last?.reps ?? widget.exercise.repMax).toString(),
    );
    _formDraft = FormDraft(
      records: LocalRecordsScope.read(context),
      key: 'set:${widget.exercise.id}:${widget.editingSet?.id ?? 'new'}',
      label: '${widget.exercise.name}训练组',
      fields: {'weight': _weight, 'reps': _reps},
      isActive: () => mounted,
      extras: () => {'imperial': _units.imperial},
      restoreExtras: (data) {
        final previous = MeasurementUnits(imperial: data['imperial'] == true);
        final kg = previous.parseWeight(_weight.text);
        if (kg != null && previous.imperial != _units.imperial) {
          _weight.text = _units.weightInput(kg);
        }
      },
      onRestored: () {
        if (mounted) setState(() {});
      },
    );
  }

  @override
  void dispose() {
    _formDraft.dispose();
    _weight.dispose();
    _reps.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    _formDraft.dispose();
    Navigator.pop(
      context,
      _SetInput(
        weightKg: _units.parseWeight(_weight.text, original: _initialWeight)!,
        reps: int.parse(_reps.text),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        top: 20,
        right: 20,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 20,
      ),
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              widget.editingSet == null
                  ? '第 ${widget.exercise.sets.length + 1} 组 · ${widget.exercise.name}'
                  : '修改第 ${widget.editingSet!.setIndex} 组 · ${widget.exercise.name}',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: TextFormField(
                    controller: _weight,
                    autofocus: true,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    inputFormatters: [
                      FilteringTextInputFormatter.allow(
                        RegExp(r'^\d*\.?\d{0,3}'),
                      ),
                    ],
                    decoration: InputDecoration(
                      labelText: '重量（${_units.weightLabel}）',
                    ),
                    validator: (value) {
                      final parsed = double.tryParse(value ?? '');
                      return parsed == null || parsed < 0 ? '请输入有效重量' : null;
                    },
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextFormField(
                    controller: _reps,
                    keyboardType: TextInputType.number,
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                    decoration: const InputDecoration(labelText: '次数'),
                    validator: (value) {
                      final parsed = int.tryParse(value ?? '');
                      return parsed == null || parsed < 0 || parsed > 1000
                          ? '请输入 0–1000'
                          : null;
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: 18),
            FilledButton(
              onPressed: _submit,
              child: Text(widget.editingSet == null ? '完成这一组' : '保存修改'),
            ),
          ],
        ),
      ),
    );
  }
}

class _ExercisePickerSheet extends StatefulWidget {
  const _ExercisePickerSheet({required this.title, required this.repository});

  final String title;
  final ExerciseRepository repository;

  @override
  State<_ExercisePickerSheet> createState() => _ExercisePickerSheetState();
}

class _ExercisePickerSheetState extends State<_ExercisePickerSheet> {
  late final Future<ExercisePageData> _future = widget.repository.list();
  String _query = '';

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.78,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(widget.title, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 12),
              TextField(
                decoration: const InputDecoration(
                  prefixIcon: Icon(Icons.search_rounded),
                  hintText: '搜索动作名称、器械或肌群',
                ),
                onChanged: (value) => setState(() => _query = value.trim()),
              ),
              const SizedBox(height: 10),
              Expanded(
                child: FutureBuilder<ExercisePageData>(
                  future: _future,
                  builder: (context, snapshot) {
                    if (!snapshot.hasData) {
                      if (snapshot.hasError) {
                        return const Center(child: Text('动作库加载失败，请稍后重试'));
                      }
                      return const Center(child: CircularProgressIndicator());
                    }
                    final keyword = _query.toLowerCase();
                    final items = snapshot.data!.items
                        .where((item) {
                          if (keyword.isEmpty) return true;
                          return item.name.toLowerCase().contains(keyword) ||
                              item.equipment.toLowerCase().contains(keyword) ||
                              item.primaryMuscles.any(
                                (muscle) =>
                                    muscle.toLowerCase().contains(keyword),
                              );
                        })
                        .toList(growable: false);
                    if (items.isEmpty) {
                      return const Center(child: Text('没有找到匹配动作'));
                    }
                    return ListView.separated(
                      itemCount: items.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (context, index) {
                        final item = items[index];
                        return ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text(item.name),
                          subtitle: Text(
                            '${item.equipment} · ${item.primaryMuscles.join('、')}',
                          ),
                          trailing: const Icon(
                            Icons.add_circle_outline_rounded,
                          ),
                          onTap: () => Navigator.pop(context, item),
                        );
                      },
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

String _formatDuration(int seconds) {
  final duration = Duration(seconds: seconds);
  final minutes = duration.inMinutes.remainder(60).toString().padLeft(2, '0');
  final secs = duration.inSeconds.remainder(60).toString().padLeft(2, '0');
  if (duration.inHours > 0) {
    return '${duration.inHours.toString().padLeft(2, '0')}:$minutes:$secs';
  }
  return '$minutes:$secs';
}

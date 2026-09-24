import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

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
    super.dispose();
  }

  Future<void> _recordSet(WorkoutExercise exercise) async {
    final input = await showModalBottomSheet<_SetInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _SetEntrySheet(exercise: exercise),
    );
    if (input == null) return;
    await widget.controller.completeSet(
      exercise: exercise,
      weightKg: input.weightKg,
      reps: input.reps,
    );
  }

  Future<void> _editSet(WorkoutExercise exercise, WorkoutSet set) async {
    final input = await showModalBottomSheet<_SetInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _SetEntrySheet(exercise: exercise, editingSet: set),
    );
    if (input == null) return;
    await widget.controller.updateSet(
      set: set,
      weightKg: input.weightKg,
      reps: input.reps,
    );
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
    final selected = await _chooseExercise(title: '临时添加动作');
    if (selected != null) await widget.controller.addExercise(selected.id);
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
            Text('训练容量 ${summary.totalVolumeKg.toStringAsFixed(1)} kg'),
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

        final elapsed = workout.elapsedAt(DateTime.now());
        final paused = workout.status == 'paused';
        return Scaffold(
          appBar: AppBar(
            title: Text(_formatDuration(elapsed)),
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
                itemBuilder: (_) => const [
                  PopupMenuItem(value: 'add', child: Text('临时添加动作')),
                  PopupMenuItem(value: 'abandon', child: Text('放弃本次训练')),
                ],
              ),
            ],
          ),
          body: ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
            children: [
              if (workout.restTimer case final timer?) ...[
                _RestTimerCard(timer: timer),
                const SizedBox(height: 12),
              ],
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
                    child: Text('这次训练还没有动作，请先在计划中添加动作。'),
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
                  ),
                ),
              const SizedBox(height: 4),
              OutlinedButton.icon(
                onPressed: widget.controller.submitting || paused
                    ? null
                    : _addExercise,
                icon: const Icon(Icons.add_rounded),
                label: const Text('临时添加动作'),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _RestTimerCard extends StatelessWidget {
  const _RestTimerCard({required this.timer});

  final WorkoutRestTimer timer;

  @override
  Widget build(BuildContext context) {
    final remaining = timer.remainingAt(DateTime.now());
    return Card(
      color: Theme.of(context).colorScheme.secondaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            const Icon(Icons.timer_outlined),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                remaining > 0 ? '休息 ${_formatDuration(remaining)}' : '可以开始下一组',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
          ],
        ),
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
  });

  final WorkoutExercise exercise;
  final bool submitting;
  final VoidCallback onRecord;
  final ValueChanged<WorkoutSet> onEditSet;
  final ValueChanged<WorkoutSet> onDeleteSet;
  final VoidCallback onReplace;
  final VoidCallback onSkip;

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
                Text('${exercise.sets.length}/${exercise.targetSets} 组'),
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
            Text(
              '${exercise.repMin}–${exercise.repMax} 次'
              '${exercise.restSeconds > 0 ? ' · 休息 ${exercise.restSeconds} 秒' : ''}',
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
                        child: Text('${set.weightKg.toStringAsFixed(1)} kg'),
                      ),
                      Text('${set.reps} 次'),
                      const SizedBox(width: 8),
                      PopupMenuButton<String>(
                        padding: EdgeInsets.zero,
                        tooltip: '训练组操作',
                        enabled: !submitting,
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
  late final TextEditingController _reps;
  final _formKey = GlobalKey<FormState>();

  @override
  void initState() {
    super.initState();
    final last = widget.editingSet ?? widget.exercise.sets.lastOrNull;
    final initialWeight = last?.weightKg ?? widget.exercise.targetLoadKg;
    _weight = TextEditingController(text: initialWeight.toStringAsFixed(1));
    _reps = TextEditingController(
      text: (last?.reps ?? widget.exercise.repMax).toString(),
    );
  }

  @override
  void dispose() {
    _weight.dispose();
    _reps.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    Navigator.pop(
      context,
      _SetInput(
        weightKg: double.parse(_weight.text),
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
                    decoration: const InputDecoration(labelText: '重量（kg）'),
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

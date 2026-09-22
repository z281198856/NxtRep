import 'dart:async';

import 'package:flutter/material.dart';

import '../../../core/network/api_exception.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../data/exercise_repository.dart';
import '../domain/exercise_models.dart';

class ExerciseLibraryPage extends StatefulWidget {
  const ExerciseLibraryPage({super.key, required this.repository});

  final ExerciseRepository repository;

  @override
  State<ExerciseLibraryPage> createState() => _ExerciseLibraryPageState();
}

class _ExerciseLibraryPageState extends State<ExerciseLibraryPage> {
  final _search = TextEditingController();
  Timer? _debounce;
  List<ExerciseListItem> _items = const [];
  String? _equipment;
  String? _error;
  bool _loading = true;

  static const _equipmentOptions = <String, String>{
    'bodyweight': '徒手',
    'barbell': '杠铃',
    'dumbbell': '哑铃',
    'machine': '固定器械',
    'cable': '绳索',
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await widget.repository.list(
        keyword: _search.text,
        equipment: _equipment,
      );
      if (!mounted) return;
      setState(() => _items = page.items);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _onSearchChanged(String _) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), _load);
  }

  Future<void> _openExercise(String id) async {
    await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) =>
            ExerciseDetailPage(repository: widget.repository, exerciseId: id),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _createExercise() async {
    final input = await showModalBottomSheet<CustomExerciseInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _CustomExerciseSheet(),
    );
    if (input == null) return;
    try {
      final created = await widget.repository.create(input);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('已添加“${created.name}”')));
      await _load();
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('动作库'),
        actions: [
          IconButton(
            tooltip: '新建自定义动作',
            onPressed: _createExercise,
            icon: const Icon(Icons.add_rounded),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 30),
          children: [
            TextField(
              controller: _search,
              onChanged: _onSearchChanged,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                labelText: '搜索动作',
                hintText: '例如：深蹲、卧推',
                prefixIcon: const Icon(Icons.search_rounded),
                suffixIcon: _search.text.isEmpty
                    ? null
                    : IconButton(
                        tooltip: '清空',
                        onPressed: () {
                          _search.clear();
                          _load();
                        },
                        icon: const Icon(Icons.close_rounded),
                      ),
              ),
            ),
            const SizedBox(height: 12),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  ChoiceChip(
                    label: const Text('全部'),
                    selected: _equipment == null,
                    onSelected: (_) {
                      setState(() => _equipment = null);
                      _load();
                    },
                  ),
                  for (final option in _equipmentOptions.entries) ...[
                    const SizedBox(width: 8),
                    ChoiceChip(
                      label: Text(option.value),
                      selected: _equipment == option.key,
                      onSelected: (_) {
                        setState(() => _equipment = option.key);
                        _load();
                      },
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: Text(
                    _loading ? '正在加载动作' : '共 ${_items.length} 个动作',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                TextButton.icon(
                  onPressed: _createExercise,
                  icon: const Icon(Icons.add_rounded),
                  label: const Text('自定义动作'),
                ),
              ],
            ),
            const SizedBox(height: 10),
            if (_error case final message?) ...[
              AppErrorCard(message: message),
              const SizedBox(height: 12),
            ],
            if (_loading && _items.isEmpty)
              const AppSurface(
                child: Center(
                  child: Padding(
                    padding: EdgeInsets.all(26),
                    child: CircularProgressIndicator(),
                  ),
                ),
              )
            else if (!_loading && _items.isEmpty)
              AppEmptyState(
                icon: Icons.fitness_center_rounded,
                title: '没有找到动作',
                message: '换个关键词或器械筛选，也可以添加自己的动作。',
                action: FilledButton.icon(
                  onPressed: _createExercise,
                  icon: const Icon(Icons.add_rounded),
                  label: const Text('添加自定义动作'),
                ),
              )
            else
              ..._items.map(
                (item) => Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _ExerciseTile(
                    item: item,
                    onTap: () => _openExercise(item.id),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _ExerciseTile extends StatelessWidget {
  const _ExerciseTile({required this.item, required this.onTap});

  final ExerciseListItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      onTap: onTap,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: item.isCustom ? AppColors.amberSoft : AppColors.indigoSoft,
              borderRadius: BorderRadius.circular(15),
            ),
            child: Icon(
              item.isCustom ? Icons.edit_note_rounded : Icons.accessibility_new,
              color: item.isCustom ? AppColors.amber : AppColors.indigo,
            ),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        item.name,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                    ),
                    if (item.isCustom) ...[
                      const SizedBox(width: 7),
                      const StatusPill(label: '自定义', color: AppColors.amber),
                    ],
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  '${equipmentLabel(item.equipment)} · '
                  '${item.primaryMuscles.map(muscleLabel).join('、')}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.labelMedium,
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right_rounded, color: AppColors.muted),
        ],
      ),
    );
  }
}

class ExerciseDetailPage extends StatefulWidget {
  const ExerciseDetailPage({
    super.key,
    required this.repository,
    required this.exerciseId,
  });

  final ExerciseRepository repository;
  final String exerciseId;

  @override
  State<ExerciseDetailPage> createState() => _ExerciseDetailPageState();
}

class _ExerciseDetailPageState extends State<ExerciseDetailPage> {
  ExerciseDetail? _detail;
  List<ExerciseHistoryItem> _history = const [];
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final values = await Future.wait<Object>([
        widget.repository.getDetail(widget.exerciseId),
        widget.repository.getHistory(widget.exerciseId),
      ]);
      if (!mounted) return;
      setState(() {
        _detail = values[0] as ExerciseDetail;
        _history = values[1] as List<ExerciseHistoryItem>;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _edit() async {
    final detail = _detail;
    if (detail == null) return;
    final input = await showModalBottomSheet<CustomExerciseInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _CustomExerciseSheet(exercise: detail),
    );
    if (input == null) return;
    try {
      final updated = await widget.repository.update(detail, input);
      if (!mounted) return;
      setState(() => _detail = updated);
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('自定义动作已更新')));
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  Future<void> _delete() async {
    final detail = _detail;
    if (detail == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除自定义动作？'),
        content: Text('“${detail.name}”将从动作库移除，此操作无法撤销。'),
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
    if (confirmed != true) return;
    try {
      await widget.repository.delete(detail);
      if (!mounted) return;
      Navigator.pop(context, true);
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final detail = _detail;
    return Scaffold(
      appBar: AppBar(
        title: Text(detail?.name ?? '动作详情'),
        actions: [
          if (detail?.isCustom ?? false) ...[
            IconButton(
              tooltip: '编辑',
              onPressed: _edit,
              icon: const Icon(Icons.edit_outlined),
            ),
            IconButton(
              tooltip: '删除',
              onPressed: _delete,
              icon: const Icon(Icons.delete_outline_rounded),
            ),
          ],
          const SizedBox(width: 8),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 30),
          children: [
            if (_loading && detail == null)
              const AppSurface(
                child: Center(
                  child: Padding(
                    padding: EdgeInsets.all(28),
                    child: CircularProgressIndicator(),
                  ),
                ),
              )
            else if (_error case final message?)
              AppErrorCard(message: message)
            else if (detail != null) ...[
              _ExerciseOverview(detail: detail),
              if (detail.instructions.isNotEmpty) ...[
                const SizedBox(height: 24),
                _InstructionSection(
                  title: '动作步骤',
                  icon: Icons.format_list_numbered_rounded,
                  items: detail.instructions,
                  numbered: true,
                ),
              ],
              if (detail.breathing.isNotEmpty) ...[
                const SizedBox(height: 16),
                _InstructionSection(
                  title: '呼吸节奏',
                  icon: Icons.air_rounded,
                  items: detail.breathing,
                ),
              ],
              if (detail.commonErrors.isNotEmpty) ...[
                const SizedBox(height: 16),
                _InstructionSection(
                  title: '常见错误',
                  icon: Icons.error_outline_rounded,
                  items: detail.commonErrors,
                  color: AppColors.primary,
                ),
              ],
              if (detail.safetyNotes.isNotEmpty) ...[
                const SizedBox(height: 16),
                _InstructionSection(
                  title: '安全提示',
                  icon: Icons.health_and_safety_outlined,
                  items: detail.safetyNotes,
                  color: AppColors.amber,
                ),
              ],
              if (detail.notes case final notes?) ...[
                if (notes.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  _InstructionSection(
                    title: '备注',
                    icon: Icons.notes_rounded,
                    items: [notes],
                  ),
                ],
              ],
              if (detail.substitutions.isNotEmpty) ...[
                const SizedBox(height: 24),
                const SectionTitle(title: '替代动作'),
                const SizedBox(height: 10),
                ...detail.substitutions.map(
                  (item) => Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: AppSurface(
                      onTap: () => Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) => ExerciseDetailPage(
                            repository: widget.repository,
                            exerciseId: item.id,
                          ),
                        ),
                      ),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 13,
                      ),
                      child: Row(
                        children: [
                          const Icon(
                            Icons.swap_horiz_rounded,
                            color: AppColors.indigo,
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  item.name,
                                  style: Theme.of(context)
                                      .textTheme
                                      .titleMedium,
                                ),
                                Text(
                                  item.reason.isEmpty
                                      ? equipmentLabel(item.equipment)
                                      : item.reason,
                                  style: Theme.of(context)
                                      .textTheme
                                      .labelMedium,
                                ),
                              ],
                            ),
                          ),
                          const Icon(
                            Icons.chevron_right_rounded,
                            color: AppColors.muted,
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 24),
              const SectionTitle(title: '最近训练'),
              const SizedBox(height: 10),
              if (_history.isEmpty)
                const AppEmptyState(
                  icon: Icons.history_rounded,
                  title: '还没有这个动作的记录',
                  message: '完成包含该动作的训练后，组数、重量和次数会显示在这里。',
                )
              else
                ..._history.map(_ExerciseHistoryCard.new),
            ],
          ],
        ),
      ),
    );
  }
}

class _ExerciseOverview extends StatelessWidget {
  const _ExerciseOverview({required this.detail});

  final ExerciseDetail detail;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      color: AppColors.darkCard,
      borderColor: AppColors.darkCard,
      padding: const EdgeInsets.all(22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StatusPill(
                label: equipmentLabel(detail.equipment),
                color: const Color(0xFFFF858A),
                icon: Icons.fitness_center_rounded,
              ),
              if (detail.difficulty case final difficulty?) ...[
                const SizedBox(width: 8),
                StatusPill(
                  label: _difficultyLabel(difficulty),
                  color: AppColors.amber,
                ),
              ],
            ],
          ),
          const SizedBox(height: 18),
          Text(
            detail.name,
            style: Theme.of(context).textTheme.headlineSmall
                ?.copyWith(color: Colors.white),
          ),
          if (detail.aliases.isNotEmpty) ...[
            const SizedBox(height: 5),
            Text(
              detail.aliases.join(' / '),
              style: Theme.of(context).textTheme.bodyMedium
                  ?.copyWith(color: Colors.white60),
            ),
          ],
          const SizedBox(height: 18),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final muscle in detail.primaryMuscles)
                _DarkTag(label: muscleLabel(muscle)),
              for (final muscle in detail.secondaryMuscles)
                _DarkTag(label: muscleLabel(muscle), secondary: true),
            ],
          ),
        ],
      ),
    );
  }
}

class _DarkTag extends StatelessWidget {
  const _DarkTag({required this.label, this.secondary = false});

  final String label;
  final bool secondary;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: secondary ? 0.08 : 0.15),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        secondary ? '$label（辅助）' : label,
        style: const TextStyle(
          color: Colors.white,
          fontSize: 12,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _InstructionSection extends StatelessWidget {
  const _InstructionSection({
    required this.title,
    required this.icon,
    required this.items,
    this.numbered = false,
    this.color = AppColors.indigo,
  });

  final String title;
  final IconData icon;
  final List<String> items;
  final bool numbered;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: color, size: 21),
              const SizedBox(width: 9),
              Text(title, style: Theme.of(context).textTheme.titleMedium),
            ],
          ),
          const SizedBox(height: 13),
          for (var index = 0; index < items.length; index++) ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 24,
                  child: Text(
                    numbered ? '${index + 1}.' : '•',
                    style: TextStyle(color: color, fontWeight: FontWeight.w700),
                  ),
                ),
                Expanded(child: Text(items[index])),
              ],
            ),
            if (index != items.length - 1) const SizedBox(height: 9),
          ],
        ],
      ),
    );
  }
}

class _ExerciseHistoryCard extends StatelessWidget {
  const _ExerciseHistoryCard(this.item);

  final ExerciseHistoryItem item;

  @override
  Widget build(BuildContext context) {
    final local = item.startedAt.toLocal();
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: AppSurface(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${local.year}年${local.month}月${local.day}日',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 9),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final set in item.sets)
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 7,
                    ),
                    decoration: BoxDecoration(
                      color: AppColors.indigoSoft,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      '${set.index}组 · ${set.weightKg.toStringAsFixed(1)} kg × ${set.reps}',
                      style: const TextStyle(
                        color: AppColors.indigo,
                        fontWeight: FontWeight.w600,
                        fontSize: 12,
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _CustomExerciseSheet extends StatefulWidget {
  const _CustomExerciseSheet({this.exercise});

  final ExerciseDetail? exercise;

  @override
  State<_CustomExerciseSheet> createState() => _CustomExerciseSheetState();
}

class _CustomExerciseSheetState extends State<_CustomExerciseSheet> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _notes;
  late final Set<String> _primaryMuscles;
  late final Set<String> _secondaryMuscles;
  late String _equipment;

  static const _muscleOptions = <String, String>{
    'chest': '胸部',
    'back': '背部',
    'shoulders': '肩部',
    'biceps': '肱二头肌',
    'triceps': '肱三头肌',
    'quadriceps': '股四头肌',
    'hamstrings': '腘绳肌',
    'gluteus': '臀肌',
    'calves': '小腿',
    'core': '核心',
    'forearms': '前臂',
  };

  @override
  void initState() {
    super.initState();
    final exercise = widget.exercise;
    _name = TextEditingController(text: exercise?.name);
    _primaryMuscles = {...?exercise?.primaryMuscles};
    _secondaryMuscles = {...?exercise?.secondaryMuscles};
    _notes = TextEditingController(text: exercise?.notes);
    _equipment = exercise?.equipment ?? 'bodyweight';
  }

  @override
  void dispose() {
    _name.dispose();
    _notes.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_primaryMuscles.isEmpty) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请至少选择一个主练肌群')));
      return;
    }
    Navigator.pop(
      context,
      CustomExerciseInput(
        name: _name.text.trim(),
        equipment: _equipment,
        primaryMuscles: _primaryMuscles.toList(growable: false),
        secondaryMuscles: _secondaryMuscles.toList(growable: false),
        notes: _notes.text.trim().isEmpty ? null : _notes.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: EdgeInsets.only(
          left: 20,
          top: 8,
          right: 20,
          bottom: MediaQuery.viewInsetsOf(context).bottom + 20,
        ),
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  widget.exercise == null ? '添加自定义动作' : '编辑自定义动作',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 6),
                Text(
                  '选择器械和主练肌群，方便在动作库中搜索和归类。',
                  style: Theme.of(context).textTheme.bodyMedium
                      ?.copyWith(color: AppColors.muted),
                ),
                const SizedBox(height: 18),
                TextFormField(
                  controller: _name,
                  decoration: const InputDecoration(labelText: '动作名称'),
                  validator: (value) =>
                      value?.trim().isEmpty ?? true ? '请输入动作名称' : null,
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: _equipment,
                  decoration: const InputDecoration(labelText: '器械'),
                  items: const [
                    DropdownMenuItem(value: 'bodyweight', child: Text('徒手')),
                    DropdownMenuItem(value: 'barbell', child: Text('杠铃')),
                    DropdownMenuItem(value: 'dumbbell', child: Text('哑铃')),
                    DropdownMenuItem(value: 'machine', child: Text('固定器械')),
                    DropdownMenuItem(value: 'cable', child: Text('绳索器械')),
                    DropdownMenuItem(value: 'kettlebell', child: Text('壶铃')),
                    DropdownMenuItem(value: 'band', child: Text('弹力带')),
                    DropdownMenuItem(value: 'other', child: Text('其他')),
                  ],
                  onChanged: (value) => _equipment = value!,
                ),
                const SizedBox(height: 12),
                Text('主练肌群', style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 7,
                  children: [
                    for (final option in _muscleOptions.entries)
                      FilterChip(
                        label: Text(option.value),
                        selected: _primaryMuscles.contains(option.key),
                        onSelected: (selected) => setState(() {
                          if (selected) {
                            _primaryMuscles.add(option.key);
                            _secondaryMuscles.remove(option.key);
                          } else {
                            _primaryMuscles.remove(option.key);
                          }
                        }),
                      ),
                  ],
                ),
                const SizedBox(height: 16),
                Text('辅助肌群（可选）', style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 7,
                  children: [
                    for (final option in _muscleOptions.entries)
                      FilterChip(
                        label: Text(option.value),
                        selected: _secondaryMuscles.contains(option.key),
                        onSelected: _primaryMuscles.contains(option.key)
                            ? null
                            : (selected) => setState(() {
                                if (selected) {
                                  _secondaryMuscles.add(option.key);
                                } else {
                                  _secondaryMuscles.remove(option.key);
                                }
                              }),
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _notes,
                  maxLines: 3,
                  decoration: const InputDecoration(labelText: '动作备注（可选）'),
                ),
                const SizedBox(height: 18),
                FilledButton(
                  onPressed: _submit,
                  child: Text(widget.exercise == null ? '添加动作' : '保存修改'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

String _difficultyLabel(String value) => switch (value) {
  'beginner' => '初级',
  'intermediate' => '中级',
  'advanced' => '高级',
  _ => value,
};

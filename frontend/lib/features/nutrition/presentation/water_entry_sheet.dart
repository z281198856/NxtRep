import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/network/api_exception.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/offline/form_draft.dart';
import '../domain/water_entry.dart';
import '../domain/nutrition_date.dart';
import 'nutrition_controller.dart';

class WaterEntrySheet extends StatefulWidget {
  const WaterEntrySheet({super.key, required this.controller});

  final NutritionController controller;

  @override
  State<WaterEntrySheet> createState() => _WaterEntrySheetState();
}

class _WaterEntrySheetState extends State<WaterEntrySheet> {
  final _form = GlobalKey<FormState>();
  final _amount = TextEditingController(text: '250');
  late final DateTime _date = widget.controller.selectedDate;
  List<WaterEntry> _entries = const [];
  bool _loading = true;
  bool _busy = false;
  String? _error;
  late final FormDraft _formDraft;

  @override
  void initState() {
    super.initState();
    _formDraft = FormDraft(
      records: LocalRecordsScope.read(context),
      key: 'water:${_date.toIso8601String()}',
      label: '${nutritionDateLabel(_date)}饮水',
      fields: {'amount': _amount},
      isActive: () => mounted,
      onRestored: () {
        if (mounted) setState(() {});
      },
    );
    _load();
  }

  @override
  void dispose() {
    _formDraft.dispose();
    _amount.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final entries = await widget.controller.listWater(_date);
      if (mounted) setState(() => _entries = entries);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    if (_busy || !(_form.currentState?.validate() ?? false)) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final consumedAt = nutritionRecordedAt(_date, 'water');
    final saved = await widget.controller.addWater(
      int.parse(_amount.text),
      consumedAt,
      draftKey: 'water:${_date.toIso8601String()}',
    );
    if (!mounted) return;
    if (saved) {
      await clearSubmittedDraft(context, 'water:${_date.toIso8601String()}');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            widget.controller.savedLocally ? '饮水已保存在本机，联网后同步' : '饮水已记录',
          ),
        ),
      );
      await _load();
    } else {
      setState(() => _error = widget.controller.errorMessage ?? '保存失败，请重试');
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _delete(WaterEntry entry) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这条饮水记录？'),
        content: Text('${entry.amountMl} ml 将从当天累计中移除。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认删除'),
          ),
        ],
      ),
    );
    if (!mounted || confirmed != true) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final deleted = await widget.controller.deleteWater(entry.id);
    if (!mounted) return;
    if (deleted) {
      await _load();
    } else {
      setState(() => _error = widget.controller.errorMessage ?? '删除失败，请重试');
    }
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    final total = _entries.fold<int>(0, (sum, entry) => sum + entry.amountMl);
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
        child: Form(
          key: _form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Icon(Icons.water_drop_rounded, color: AppColors.indigo),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      '记饮水',
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                  ),
                  IconButton(
                    tooltip: '关闭',
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text('记录至 ${nutritionDateLabel(_date)}'),
              Text(
                _loading
                    ? '正在读取饮水记录…'
                    : _error == null
                    ? '当天已喝 $total ml'
                    : '饮水记录暂未更新',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 20),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final ml in [150, 250, 500])
                    ChoiceChip(
                      label: Text('$ml ml'),
                      selected: _amount.text == '$ml',
                      onSelected: _busy
                          ? null
                          : (_) => setState(() => _amount.text = '$ml'),
                    ),
                ],
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _amount,
                enabled: !_busy,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: const InputDecoration(
                  labelText: '本次饮水量',
                  suffixText: 'ml',
                ),
                onChanged: (_) => setState(() {}),
                validator: (value) {
                  final amount = int.tryParse(value ?? '');
                  return amount == null || amount < 1 || amount > 5000
                      ? '请输入 1–5000 ml'
                      : null;
                },
              ),
              if (_error case final message?) ...[
                const SizedBox(height: 12),
                Text(
                  message,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
                TextButton(
                  onPressed: _busy ? null : _load,
                  child: const Text('重新加载饮水记录'),
                ),
              ],
              const SizedBox(height: 18),
              FilledButton.icon(
                onPressed: _busy || _loading ? null : _save,
                icon: const Icon(Icons.add_rounded),
                label: Text(_busy ? '正在保存…' : '保存饮水'),
              ),
              const SizedBox(height: 20),
              Text('当天饮水记录', style: Theme.of(context).textTheme.titleMedium),
              if (!_loading && _error == null && _entries.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 16),
                  child: Text('还没有饮水记录，喝完一杯再来记。'),
                ),
              for (final entry in _entries)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(
                    Icons.water_drop_outlined,
                    color: AppColors.indigo,
                  ),
                  title: Text('${entry.amountMl} ml'),
                  subtitle: Text(
                    TimeOfDay.fromDateTime(
                      entry.consumedAt.toUtc().add(const Duration(hours: 8)),
                    ).format(context),
                  ),
                  trailing: IconButton(
                    tooltip: '删除饮水记录',
                    onPressed: _busy ? null : () => _delete(entry),
                    icon: const Icon(Icons.delete_outline_rounded),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

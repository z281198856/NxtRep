import 'package:flutter/material.dart';

import '../../../core/network/api_exception.dart';
import '../domain/nutrition_date.dart';
import '../domain/nutrition_models.dart';
import 'nutrition_controller.dart';

class NutritionCopySheet extends StatefulWidget {
  const NutritionCopySheet({
    super.key,
    required this.controller,
    required this.recordDate,
  });
  final NutritionController controller;
  final DateTime recordDate;

  @override
  State<NutritionCopySheet> createState() => _NutritionCopySheetState();
}

class _NutritionCopySheetState extends State<NutritionCopySheet> {
  List<NutritionEntry> _entries = const [];
  NutritionEntry? _selected;
  String _mealType = 'lunch';
  String? _error;
  bool _loading = true;
  bool _saving = false;
  static const _meals = {
    'breakfast': '早餐',
    'lunch': '午餐',
    'dinner': '晚餐',
    'snack': '加餐',
    'other': '其他',
  };

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
      final entries = await widget.controller.recentEntries(widget.recordDate);
      if (mounted) setState(() => _entries = entries);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    final entry = _selected;
    if (entry == null || _saving) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    final saved = await widget.controller.copyEntry(
      entry,
      _mealType,
      widget.recordDate,
    );
    if (!mounted) return;
    if (saved) {
      Navigator.pop(context);
    } else {
      setState(() {
        _saving = false;
        _error = widget.controller.errorMessage ?? '复制失败，请重试';
      });
    }
  }

  @override
  Widget build(BuildContext context) => SizedBox(
    height: MediaQuery.sizeOf(context).height * .78,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 8, 4),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  _selected == null ? '选择最近餐食' : '确认复制餐食',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              IconButton(
                tooltip: '关闭',
                onPressed: _saving ? null : () => Navigator.pop(context),
                icon: const Icon(Icons.close),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: Text('记录至 ${nutritionDateLabel(widget.recordDate)}'),
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (_loading) const LinearProgressIndicator(),
        Expanded(
          child: _selected == null
              ? _entries.isEmpty
                    ? Center(
                        child: _loading
                            ? const Text('正在读取最近餐食…')
                            : Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Text(
                                    _error == null
                                        ? '这一天及之前还没有可复制的餐食'
                                        : '未能读取最近餐食',
                                  ),
                                  if (_error != null)
                                    TextButton(
                                      onPressed: _load,
                                      child: const Text('重试'),
                                    ),
                                ],
                              ),
                      )
                    : ListView.builder(
                        itemCount: _entries.length,
                        itemBuilder: (context, index) {
                          final entry = _entries[index];
                          final day = entry.eatenAt.toUtc().add(
                            const Duration(hours: 8),
                          );
                          return ListTile(
                            title: Text(
                              entry.displayName,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                            subtitle: Text(
                              '${day.month}月${day.day}日 · ${_meals[entry.mealType] ?? '其他'} · ${entry.totals.kcal.toStringAsFixed(0)} 千卡',
                            ),
                            trailing: const Icon(Icons.chevron_right),
                            onTap: () => setState(() {
                              _selected = entry;
                              _mealType = entry.mealType;
                              _error = null;
                            }),
                          );
                        },
                      )
              : ListView(
                  padding: const EdgeInsets.all(20),
                  children: [
                    DropdownButtonFormField<String>(
                      initialValue: _mealType,
                      decoration: const InputDecoration(labelText: '记录到哪一餐'),
                      items: _meals.entries
                          .map(
                            (e) => DropdownMenuItem(
                              value: e.key,
                              child: Text(e.value),
                            ),
                          )
                          .toList(),
                      onChanged: _saving
                          ? null
                          : (value) => setState(() => _mealType = value!),
                    ),
                    const SizedBox(height: 16),
                    ..._selected!.items.map(
                      (item) => ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(item.name),
                        trailing: Text('${item.amountG.toStringAsFixed(0)} g'),
                      ),
                    ),
                    Text(
                      '合计 ${_selected!.totals.kcal.toStringAsFixed(0)} 千卡 · 沿用原餐食份量及营养值',
                    ),
                    const SizedBox(height: 16),
                    FilledButton.icon(
                      onPressed: _saving ? null : _save,
                      icon: const Icon(Icons.check),
                      label: Text(_saving ? '正在保存…' : '确认复制'),
                    ),
                    TextButton(
                      onPressed: _saving
                          ? null
                          : () => setState(() {
                              _selected = null;
                              _error = null;
                            }),
                      child: const Text('重新选择餐食'),
                    ),
                  ],
                ),
        ),
      ],
    ),
  );
}

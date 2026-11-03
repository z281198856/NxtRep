import 'package:flutter/material.dart';

import 'local_records.dart';
import '../settings/app_preferences.dart';

class LocalRecordsPage extends StatelessWidget {
  const LocalRecordsPage({
    super.key,
    required this.records,
    required this.onSync,
    this.onOpenDraft,
  });
  final LocalRecords records;
  final Future<void> Function() onSync;
  final Future<void> Function(String key)? onOpenDraft;

  double? _number(Object? value) =>
      value == null ? null : double.tryParse(value.toString());

  String _title(BuildContext context, LocalRecord entry) {
    final units = AppPreferencesScope.unitsOf(context);
    if (entry.path.startsWith('/workouts/')) {
      return '${entry.exerciseName ?? '训练组'} · 第 ${entry.body['set_index']} 组 · '
          '${units.formatWeight(_number(entry.body['weight_kg']) ?? 0)} × ${entry.body['reps']}';
    }
    if (entry.path == '/body/measurements') {
      final parts = <String>[];
      final weight = _number(entry.body['weight_kg']);
      final fat = _number(entry.body['body_fat_percent']);
      if (weight != null) parts.add('体重 ${units.formatWeight(weight)}');
      if (fat != null) parts.add('体脂 ${fat.toStringAsFixed(1)}%');
      return parts.isEmpty ? '身体测量' : parts.join(' · ');
    }
    return entry.label;
  }

  String _detail(BuildContext context, LocalRecord entry) {
    final units = AppPreferencesScope.unitsOf(context);
    final body = entry.body;
    final parts = <String>[];
    for (final field in {
      'waist_cm': '腰围',
      'neck_cm': '颈围',
      'hip_cm': '臀围',
    }.entries) {
      final value = _number(body[field.key]);
      if (value != null) {
        parts.add('${field.value} ${units.formatLength(value)}');
      }
    }
    for (final item in body['items'] as List? ?? []) {
      parts.add('${item['name'] ?? '食品'} ${item['amount_g']} g');
    }
    if (body['conditions'] is String &&
        (body['conditions'] as String).isNotEmpty) {
      parts.add('测量条件：${body['conditions']}');
    }
    if (body['notes'] is String && (body['notes'] as String).isNotEmpty) {
      parts.add('备注：${body['notes']}');
    }
    return parts.join('；');
  }

  Future<void> _discard(
    BuildContext context,
    String key, {
    bool draft = false,
  }) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(draft ? '删除这份草稿？' : '移除这条待同步记录？'),
        content: Text(
          draft ? '只删除本机草稿。' : '若上次提交结果不确定，请先核对对应日期的记录；移除不会撤销已保存的正式记录。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认移除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      if (draft) {
        await records.saveDraft(key, '', null);
      } else {
        await records.discard(key);
      }
    } on Object {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('本机保存失败，内容已保留，请重试')));
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('离线记录与草稿')),
    body: ListenableBuilder(
      listenable: records,
      builder: (context, _) => ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            '待同步 ${records.pending.length} 条',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          const Text(
            '联网后自动尝试同步。未同步的记录尚未计入统计；出现冲突时会保留内容，供你核对。已开始训练可离线记组，开始新训练和结束训练需要联网。',
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: records.syncing ? null : onSync,
            icon: const Icon(Icons.sync),
            label: Text(records.syncing ? '正在同步…' : '立即同步'),
          ),
          if (records.localOnly) const Text('当前使用本机内容，联网后将先核实登录状态。'),
          if (records.storageError case final error?)
            Text(
              error,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          for (final entry in records.pending)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _title(context, entry),
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    if (_detail(context, entry).isNotEmpty)
                      SelectableText(_detail(context, entry)),
                    Text(
                      '记录时间：${DateTime.parse(entry.recordedAt).toLocal().toString().substring(0, 16)}',
                    ),
                    Text(
                      entry.issue ?? '已保存在本机 · 等待同步',
                      style: TextStyle(
                        color: entry.issue == null
                            ? null
                            : Theme.of(context).colorScheme.error,
                      ),
                    ),
                    if (entry.issue != null)
                      const Text('请先到对应日期核对记录。为避免覆盖或重复，不会自动重试此条。'),
                    TextButton(
                      onPressed: records.syncing
                          ? null
                          : () => _discard(context, entry.key),
                      child: const Text('移除待同步项'),
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 24),
          Text(
            '未提交草稿 ${records.drafts.length} 份',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const Text(
            '再次打开相同日期、餐次的录入表单或拍照入口会恢复草稿。AI 输入框会恢复未发送文字。恢复草稿不会自动识别、发送或保存正式记录。',
          ),
          for (final entry in records.drafts.entries)
            ListTile(
              onTap: onOpenDraft == null ? null : () => onOpenDraft!(entry.key),
              subtitle: const Text('点击继续填写'),
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.edit_note),
              title: Text((entry.value as Map)['label'] as String),
              trailing: IconButton(
                tooltip: '删除草稿',
                icon: const Icon(Icons.delete_outline),
                onPressed: () => _discard(context, entry.key, draft: true),
              ),
            ),
          const SizedBox(height: 16),
          const Text(
            '本机内容按账户和服务器分别保存；退出登录后隐藏，同一账户登录后恢复。卸载应用或清除应用数据会丢失尚未同步的内容。',
          ),
        ],
      ),
    ),
  );
}

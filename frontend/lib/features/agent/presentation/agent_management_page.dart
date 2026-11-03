import 'dart:async';

import 'package:flutter/material.dart';

import '../../../core/widgets/app_widgets.dart';
import '../domain/agent_models.dart';
import 'agent_controller.dart';
import 'conversation_history.dart';

class AgentManagementPage extends StatelessWidget {
  const AgentManagementPage({super.key, required this.controller});

  final AgentController controller;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('对话与记忆'),
          bottom: const TabBar(
            tabs: [
              Tab(text: '历史对话'),
              Tab(text: '长期记忆'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            _ConversationTab(controller: controller),
            _MemoryTab(controller: controller),
          ],
        ),
      ),
    );
  }
}

class _ConversationTab extends StatefulWidget {
  const _ConversationTab({required this.controller});

  final AgentController controller;

  @override
  State<_ConversationTab> createState() => _ConversationTabState();
}

class _ConversationTabState extends State<_ConversationTab> {
  bool _archived = false;
  bool _loading = true;
  List<AgentConversation> _items = const [];
  String? _error;
  int _loadGeneration = 0;
  int _titleRefreshes = 0;
  Timer? _titleRefresh;
  final Set<String> _busy = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _loadGeneration++;
    _titleRefresh?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    _titleRefresh?.cancel();
    final generation = ++_loadGeneration;
    if (!silent) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    final items = await widget.controller.listConversations(
      status: _archived ? 'archived' : 'active',
    );
    if (!mounted || generation != _loadGeneration) return;
    setState(() {
      _items = items;
      _error = widget.controller.errorMessage;
      _loading = false;
    });
    // Refresh a few times while background titles finish, without hiding the list.
    if (_error == null &&
        _titleRefreshes < 3 &&
        items.any(
          (item) =>
              item.lastMessageAt != null &&
              (item.titleSource == 'fallback' ||
                  item.title == null ||
                  item.title == '训练咨询'),
        )) {
      _titleRefreshes++;
      _titleRefresh = Timer(
        const Duration(seconds: 3),
        () => _load(silent: true),
      );
    }
  }

  Future<void> _open(AgentConversation item) async {
    if (_archived || _busy.contains(item.id)) return;
    setState(() {
      _busy.add(item.id);
      _error = null;
    });
    final opened = await widget.controller.openConversation(item);
    if (!mounted) return;
    if (opened) {
      Navigator.pop(context);
    } else {
      setState(() {
        _busy.remove(item.id);
        _error = widget.controller.errorMessage;
      });
    }
  }

  Future<void> _rename(AgentConversation item) async {
    final title = await showDialog<String>(
      context: context,
      builder: (_) =>
          _ConversationRenameDialog(initialTitle: item.displayTitle),
    );
    if (title == null || title.isEmpty) return;
    await _change(
      item,
      () => widget.controller.renameConversation(item, title),
    );
  }

  Future<void> _change(
    AgentConversation item,
    Future<bool> Function() action, {
    String? successMessage,
  }) async {
    if (!mounted || _busy.contains(item.id)) return;
    setState(() {
      _busy.add(item.id);
      _error = null;
    });
    final success = await action();
    if (!mounted) return;
    setState(() {
      _busy.remove(item.id);
      _error = success ? null : widget.controller.errorMessage ?? '操作没有完成，请重试。';
    });
    if (success) {
      if (successMessage != null) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(successMessage)));
      }
      await _load(silent: true);
    }
  }

  Future<void> _delete(AgentConversation item) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这段对话？'),
        content: const Text('消息记录会被永久删除。'),
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
    if (confirmed == true) {
      await _change(item, () => widget.controller.deleteConversation(item));
    }
  }

  Widget _conversationRow(AgentConversation item) {
    final busy = _busy.contains(item.id);
    final time = conversationTimeLabel(item);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: AppSurface(
        onTap: busy || _archived ? null : () => _open(item),
        padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
        child: Row(
          children: [
            Icon(
              _archived
                  ? Icons.inventory_2_outlined
                  : Icons.chat_bubble_outline_rounded,
              size: 22,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.displayTitle,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  if (time.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(time, style: Theme.of(context).textTheme.bodySmall),
                  ],
                ],
              ),
            ),
            if (busy)
              const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            else
              PopupMenuButton<String>(
                tooltip: '对话操作',
                enabled: !widget.controller.sending,
                onSelected: (value) async {
                  if (value == 'rename') await _rename(item);
                  if (value == 'archive') {
                    await _change(
                      item,
                      () => widget.controller.archiveConversation(item),
                      successMessage: '已归档，可以在“已归档”中找回。',
                    );
                  }
                  if (value == 'restore') {
                    await _change(
                      item,
                      () => widget.controller.restoreConversation(item),
                      successMessage: '已恢复，可以继续这段对话。',
                    );
                  }
                  if (value == 'delete') await _delete(item);
                },
                itemBuilder: (_) => [
                  if (!_archived)
                    const PopupMenuItem(value: 'rename', child: Text('重命名')),
                  if (!_archived)
                    const PopupMenuItem(value: 'archive', child: Text('归档')),
                  if (_archived)
                    const PopupMenuItem(value: 'restore', child: Text('恢复对话')),
                  const PopupMenuItem(value: 'delete', child: Text('删除')),
                ],
              ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      final groups = groupConversationsByDay(_items);
      return Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 14, 20, 8),
            child: Row(
              children: [
                Expanded(
                  child: SegmentedButton<bool>(
                    segments: const [
                      ButtonSegment(value: false, label: Text('对话')),
                      ButtonSegment(value: true, label: Text('已归档')),
                    ],
                    selected: {_archived},
                    onSelectionChanged: (value) {
                      setState(() {
                        _archived = value.first;
                        _titleRefreshes = 0;
                      });
                      _load();
                    },
                  ),
                ),
                const SizedBox(width: 10),
                TextButton.icon(
                  onPressed: widget.controller.sending || _busy.isNotEmpty
                      ? null
                      : () {
                          widget.controller.startNewConversation();
                          Navigator.pop(context);
                        },
                  icon: const Icon(Icons.edit_square, size: 18),
                  label: const Text('新建对话'),
                ),
              ],
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  AppErrorCard(message: _error!),
                  TextButton(onPressed: _load, child: const Text('刷新列表')),
                ],
              ),
            ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : RefreshIndicator(
                    onRefresh: () {
                      _titleRefreshes = 0;
                      return _load();
                    },
                    child: ListView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                      children: [
                        if (_items.isEmpty && _error == null)
                          AppEmptyState(
                            icon: Icons.forum_outlined,
                            title: _archived ? '没有已归档对话' : '还没有历史对话',
                            message: _archived
                                ? '归档后会保留聊天内容，也可以随时恢复。'
                                : '和 AI 私人教练聊过的话题会显示在这里。',
                          ),
                        for (final group in groups) ...[
                          Padding(
                            padding: const EdgeInsets.fromLTRB(2, 12, 0, 10),
                            child: Text(
                              group.label,
                              style: Theme.of(context).textTheme.titleSmall,
                            ),
                          ),
                          for (final item in group.items)
                            _conversationRow(item),
                        ],
                      ],
                    ),
                  ),
          ),
        ],
      );
    },
  );
}

class _MemoryTab extends StatefulWidget {
  const _MemoryTab({required this.controller});

  final AgentController controller;

  @override
  State<_MemoryTab> createState() => _MemoryTabState();
}

class _MemoryTabState extends State<_MemoryTab> {
  static const categories = <String, String>{
    'long_term_goal': '长期目标',
    'equipment': '可用器械',
    'schedule': '训练时间',
    'allergy': '过敏信息',
    'dietary_preference': '饮食偏好',
    'exercise_limit': '动作限制',
    'communication_preference': '沟通偏好',
    'other': '其他',
  };

  bool _loading = true;
  List<AgentMemory> _items = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final items = await widget.controller.listMemories();
    if (!mounted) return;
    setState(() {
      _items = items;
      _loading = false;
    });
  }

  Future<void> _edit([AgentMemory? memory]) async {
    final result = await showDialog<(String, String)>(
      context: context,
      builder: (_) =>
          _MemoryEditorDialog(memory: memory, categories: categories),
    );
    if (result == null || result.$2.isEmpty) return;
    final saved = memory == null
        ? await widget.controller.createMemory(
            category: result.$1,
            content: result.$2,
          )
        : await widget.controller.updateMemory(
            memory,
            category: result.$1,
            content: result.$2,
          );
    if (saved) await _load();
  }

  Future<void> _delete(AgentMemory memory) async {
    if (await widget.controller.deleteMemory(memory)) await _load();
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _edit,
        icon: const Icon(Icons.add_rounded),
        label: const Text('新增记忆'),
      ),
      body: _items.isEmpty
          ? const AppEmptyState(
              icon: Icons.psychology_alt_outlined,
              title: '还没有长期记忆',
              message: '保存目标、器械、饮食偏好或动作限制，AI 建议会更贴合你。',
            )
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView.separated(
                padding: const EdgeInsets.fromLTRB(20, 14, 20, 96),
                itemCount: _items.length,
                separatorBuilder: (_, _) => const SizedBox(height: 10),
                itemBuilder: (context, index) {
                  final item = _items[index];
                  return AppSurface(
                    padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(categories[item.category] ?? '其他'),
                              const SizedBox(height: 4),
                              Text(item.content),
                            ],
                          ),
                        ),
                        PopupMenuButton<String>(
                          onSelected: (value) {
                            if (value == 'edit') _edit(item);
                            if (value == 'delete') _delete(item);
                          },
                          itemBuilder: (_) => const [
                            PopupMenuItem(value: 'edit', child: Text('编辑')),
                            PopupMenuItem(value: 'delete', child: Text('删除')),
                          ],
                        ),
                      ],
                    ),
                  );
                },
              ),
            ),
    );
  }
}

class _ConversationRenameDialog extends StatefulWidget {
  const _ConversationRenameDialog({required this.initialTitle});

  final String initialTitle;

  @override
  State<_ConversationRenameDialog> createState() =>
      _ConversationRenameDialogState();
}

class _ConversationRenameDialogState extends State<_ConversationRenameDialog> {
  late final TextEditingController _title;

  @override
  void initState() {
    super.initState();
    _title = TextEditingController(text: widget.initialTitle);
  }

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('重命名对话'),
      content: TextField(
        controller: _title,
        autofocus: true,
        decoration: const InputDecoration(labelText: '对话名称'),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () {
            FocusManager.instance.primaryFocus?.unfocus();
            Navigator.pop(context, _title.text.trim());
          },
          child: const Text('保存'),
        ),
      ],
    );
  }
}

class _MemoryEditorDialog extends StatefulWidget {
  const _MemoryEditorDialog({required this.memory, required this.categories});

  final AgentMemory? memory;
  final Map<String, String> categories;

  @override
  State<_MemoryEditorDialog> createState() => _MemoryEditorDialogState();
}

class _MemoryEditorDialogState extends State<_MemoryEditorDialog> {
  late final TextEditingController _content;
  late String _category;

  @override
  void initState() {
    super.initState();
    _category = widget.memory?.category ?? 'other';
    _content = TextEditingController(text: widget.memory?.content);
  }

  @override
  void dispose() {
    _content.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.memory == null ? '新增长期记忆' : '编辑长期记忆'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          DropdownButtonFormField<String>(
            initialValue: _category,
            decoration: const InputDecoration(labelText: '类型'),
            items: widget.categories.entries
                .map(
                  (entry) => DropdownMenuItem(
                    value: entry.key,
                    child: Text(entry.value),
                  ),
                )
                .toList(growable: false),
            onChanged: (value) => setState(() => _category = value!),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _content,
            autofocus: true,
            minLines: 2,
            maxLines: 5,
            decoration: const InputDecoration(labelText: '希望 AI 记住的内容'),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () {
            FocusManager.instance.primaryFocus?.unfocus();
            Navigator.pop(context, (_category, _content.text.trim()));
          },
          child: const Text('保存'),
        ),
      ],
    );
  }
}

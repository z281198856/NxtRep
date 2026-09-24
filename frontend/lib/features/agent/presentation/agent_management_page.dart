import 'package:flutter/material.dart';

import '../../../core/widgets/app_widgets.dart';
import '../domain/agent_models.dart';
import 'agent_controller.dart';

class AgentManagementPage extends StatelessWidget {
  const AgentManagementPage({super.key, required this.controller});

  final AgentController controller;

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('AI 教练管理'),
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

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (mounted) setState(() => _loading = true);
    final items = await widget.controller.listConversations(
      status: _archived ? 'archived' : 'active',
    );
    if (!mounted) return;
    setState(() {
      _items = items;
      _loading = false;
    });
  }

  Future<void> _rename(AgentConversation item) async {
    final title = await showDialog<String>(
      context: context,
      builder: (_) =>
          _ConversationRenameDialog(initialTitle: item.title ?? '训练咨询'),
    );
    if (title == null || title.isEmpty) return;
    if (await widget.controller.renameConversation(item, title)) await _load();
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
    if (confirmed == true && await widget.controller.deleteConversation(item)) {
      await _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 14, 20, 8),
          child: Row(
            children: [
              Expanded(
                child: SegmentedButton<bool>(
                  segments: const [
                    ButtonSegment(value: false, label: Text('进行中')),
                    ButtonSegment(value: true, label: Text('已归档')),
                  ],
                  selected: {_archived},
                  onSelectionChanged: (value) {
                    setState(() => _archived = value.first);
                    _load();
                  },
                ),
              ),
              const SizedBox(width: 10),
              IconButton.filledTonal(
                tooltip: '新对话',
                onPressed: () {
                  widget.controller.startNewConversation();
                  Navigator.pop(context);
                },
                icon: const Icon(Icons.add_comment_outlined),
              ),
            ],
          ),
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _items.isEmpty
              ? AppEmptyState(
                  icon: Icons.forum_outlined,
                  title: _archived ? '没有已归档对话' : '还没有历史对话',
                  message: '与 AI 教练交流后，会话会显示在这里。',
                )
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView.separated(
                    padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                    itemCount: _items.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 10),
                    itemBuilder: (context, index) {
                      final item = _items[index];
                      return AppSurface(
                        onTap: _archived
                            ? null
                            : () async {
                                if (await widget.controller.openConversation(
                                      item,
                                    ) &&
                                    context.mounted) {
                                  Navigator.pop(context);
                                }
                              },
                        padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
                        child: Row(
                          children: [
                            const Icon(Icons.chat_bubble_outline_rounded),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(item.title ?? '训练咨询'),
                                  if (item.summary case final summary?)
                                    Text(
                                      summary,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                ],
                              ),
                            ),
                            PopupMenuButton<String>(
                              onSelected: (value) async {
                                if (value == 'rename') await _rename(item);
                                if (value == 'archive' &&
                                    await widget.controller.archiveConversation(
                                      item,
                                    )) {
                                  await _load();
                                }
                                if (value == 'delete') await _delete(item);
                              },
                              itemBuilder: (_) => [
                                if (!_archived)
                                  const PopupMenuItem(
                                    value: 'rename',
                                    child: Text('重命名'),
                                  ),
                                if (!_archived)
                                  const PopupMenuItem(
                                    value: 'archive',
                                    child: Text('归档'),
                                  ),
                                const PopupMenuItem(
                                  value: 'delete',
                                  child: Text('删除'),
                                ),
                              ],
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
        ),
      ],
    );
  }
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

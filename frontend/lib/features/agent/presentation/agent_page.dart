import '../../../core/settings/app_preferences.dart';
import 'source_links.dart';

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/media/image_upload.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/offline/form_draft.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/agent_models.dart';
import 'agent_controller.dart';
import 'agent_management_page.dart';
import 'agent_reply_format.dart';

class AgentPage extends StatefulWidget {
  const AgentPage({super.key, required this.controller});

  final AgentController controller;

  @override
  State<AgentPage> createState() => _AgentPageState();
}

class _AgentPageState extends State<AgentPage> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _focusNode = FocusNode();
  final _imagePicker = ImagePicker();
  Timer? _scrollThrottle;
  bool _followTail = true;
  late final FormDraft _inputDraft;
  bool _needsReview = false;

  @override
  void initState() {
    super.initState();
    _inputDraft = FormDraft(records: LocalRecordsScope.read(context), key: 'agent-input', label: 'AI 未发送文字',
      fields: {'text': _input}, isActive: () => mounted,
      extras: () => {'review_required': _needsReview},
      restoreExtras: (data) { _needsReview = data['review_required'] == true; },
      onRestored: () { if (mounted) setState(() {}); });
    widget.controller.addListener(_scheduleScrollToEnd);
    unawaited(_recoverLostImages());
  }

  @override
  void dispose() {
    _inputDraft.dispose();
    widget.controller.removeListener(_scheduleScrollToEnd);
    _scrollThrottle?.cancel();
    _input.dispose();
    _focusNode.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _trackScrollPosition() {
    if (!_scroll.hasClients) return;
    final followTail =
        _scroll.position.maxScrollExtent - _scroll.position.pixels < 120;
    if (_followTail != followTail) setState(() => _followTail = followTail);
  }

  void _scheduleScrollToEnd() {
    if (widget.controller.openingConversation) _followTail = true;
    if (!_followTail || _scrollThrottle?.isActive == true) return;
    _scrollThrottle = Timer(const Duration(milliseconds: 70), () {
      unawaited(_settleScrollToEnd());
    });
  }

  Future<void> _settleScrollToEnd() async {
    // A lazy list refines its extent while older messages/cards are built.
    // Bound the follow-up frames and yield immediately to a user's scroll.
    for (var attempt = 0; attempt < 6; attempt++) {
      await WidgetsBinding.instance.endOfFrame;
      if (!mounted || !_scroll.hasClients || !_followTail) return;
      final target = _scroll.position.maxScrollExtent;
      if (attempt > 0 && (_scroll.position.pixels - target).abs() < 1) return;
      _scroll.jumpTo(target);
    }
  }

  Future<void> _send([String? suggested]) async {
    final text = suggested ?? _input.text;
    if ((text.trim().isEmpty && widget.controller.attachedImages.isEmpty) ||
        widget.controller.sending ||
        widget.controller.uploadingImage) {
      return;
    }
    if (_needsReview) {
      final resend = await showDialog<bool>(context: context, builder: (context) => AlertDialog(
        title: const Text('先核对上次对话结果'),
        content: const Text('这份草稿上次可能已经发送，请先在历史聊天中核对回复和待确认卡，避免重复操作。'),
        actions: [TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('返回核对')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('确认重新发送'))],
      ));
      if (!mounted || resend != true) return;
    }
    final records = LocalRecordsScope.read(context);
    try {
      await records?.saveDraft('agent-input', 'AI 待核对的发送内容', {'text': text, 'review_required': true});
    } on Object {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('发送草稿保存失败，请稍后重试')));
      return;
    }
    if (!mounted) return;
    _inputDraft.suspended = true;
    _input.clear();
    _focusNode.unfocus();
    _followTail = true;
    await widget.controller.send(text);
    if (!mounted) return;
    if (widget.controller.errorMessage == null) {
      _needsReview = false;
      await records?.saveDraft('agent-input', '', null);
    } else {
      _needsReview = true;
      _input.text = text;
    }
    _inputDraft.suspended = false;
  }

  Future<void> _recoverLostImages() async {
    try {
      final records = LocalRecordsScope.read(context);
      // The food-photo page owns a pending camera result; do not consume it as
      // an AI attachment when the shell recreates all tabs after an OS restart.
      if (records != null) {
        for (final key in records.drafts.keys.where((key) => key.startsWith('photo:'))) {
          if ((await records.readDraft(key))?['picker_pending'] == true) return;
        }
      }
      final response = await _imagePicker.retrieveLostData();
      final files = response.files;
      if (files == null) {
        if (response.exception != null) {
          widget.controller.reportImagePickerError();
        }
        return;
      }
      await _uploadFiles(files);
    } on Object {
      widget.controller.reportImagePickerError();
    }
  }

  Future<void> _chooseImages(ImageSource source) async {
    if (!widget.controller.canAttachImage) return;
    try {
      final remaining = 4 - widget.controller.attachedImages.length;
      if (source == ImageSource.camera) {
        final image = await _imagePicker.pickImage(
          source: source,
          maxWidth: 2048,
          maxHeight: 2048,
          imageQuality: 86,
          requestFullMetadata: false,
        );
        if (image != null) await _uploadFiles([image]);
      } else {
        final images = await _imagePicker.pickMultiImage(
          limit: remaining,
          maxWidth: 2048,
          maxHeight: 2048,
          imageQuality: 86,
          requestFullMetadata: false,
        );
        await _uploadFiles(images);
      }
    } on Object {
      widget.controller.reportImagePickerError();
    }
  }

  Future<void> _uploadFiles(List<XFile> files) async {
    for (final file in files) {
      if (!widget.controller.canAttachImage) break;
      try {
        await widget.controller.addImageBytes(await file.readAsBytes());
      } on Object {
        widget.controller.reportImagePickerError();
        break;
      }
    }
  }

  Future<void> _showImageSourceSheet() async {
    _focusNode.unfocus();
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                '发送照片给 AI 私人教练',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 8),
              Text(
                '可识别食物、身体变化和训练计划截图，最多选择 4 张。',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              const SizedBox(height: 14),
              ListTile(
                leading: const Icon(Icons.camera_alt_outlined),
                title: const Text('拍照'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  unawaited(_chooseImages(ImageSource.camera));
                },
              ),
              ListTile(
                leading: const Icon(Icons.photo_library_outlined),
                title: const Text('从相册选择'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  unawaited(_chooseImages(ImageSource.gallery));
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _openManagement() {
    _focusNode.unfocus();
    return Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => AgentManagementPage(controller: widget.controller),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) {
            final items = widget.controller.conversationItems;
            return Column(
              children: [
                _CoachHeader(
                  title:
                      widget.controller.currentConversation?.title ?? 'AI 私人教练',
                  onManage: _openManagement,
                  onNewConversation: widget.controller.startNewConversation,
                ),
                Expanded(
                  child: widget.controller.messages.isEmpty
                      ? _Welcome(onPrompt: _send)
                      : NotificationListener<ScrollNotification>(
                          onNotification: (notification) {
                            if (notification is UserScrollNotification ||
                                notification is ScrollUpdateNotification &&
                                    notification.dragDetails != null) {
                              _trackScrollPosition();
                            }
                            return false;
                          },
                          child: ListView.builder(
                            controller: _scroll,
                            padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                            itemCount: items.length,
                            itemBuilder: (context, index) {
                              final item = items[index];
                              if (item is AgentMessage) {
                                return _MessageBubble(
                                  message: item,
                                  activityLabel:
                                      item.id ==
                                          widget.controller.messages.last.id
                                      ? widget.controller.activityLabel
                                      : null,
                                );
                              }
                              return _ConfirmationCard(
                                card: item as AgentConfirmationCard,
                                controller: widget.controller,
                              );
                            },
                          ),
                        ),
                ),
                if (!_followTail && widget.controller.messages.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: ActionChip(
                      avatar: const Icon(
                        Icons.arrow_downward_rounded,
                        size: 17,
                      ),
                      label: const Text('回到最新回复'),
                      onPressed: () {
                        _followTail = true;
                        if (_scroll.hasClients) {
                          _scroll.animateTo(
                            _scroll.position.maxScrollExtent,
                            duration: const Duration(milliseconds: 220),
                            curve: Curves.easeOut,
                          );
                        }
                      },
                    ),
                  ),
                if (widget.controller.errorMessage case final message?)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                    child: AppErrorCard(message: message),
                  ),
                if (widget.controller.canRetryLastTurn)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                    child: TextButton.icon(
                      onPressed: widget.controller.retryLastTurn,
                      icon: const Icon(Icons.refresh_rounded, size: 18),
                      label: const Text('核实上次结果'),
                    ),
                  ),
                if (widget.controller.statusMessage case final message?)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                    child: AppSurface(
                      padding: const EdgeInsets.all(12),
                      child: Row(
                        children: [
                          const Icon(
                            Icons.check_circle_outline,
                            color: AppColors.mint,
                            size: 20,
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              message,
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                _Composer(
                  controller: _input,
                  focusNode: _focusNode,
                  sending: widget.controller.sending,
                  uploadingImage: widget.controller.uploadingImage,
                  attachedImages: widget.controller.attachedImages,
                  pendingImageBytes: widget.controller.pendingImageBytes,
                  canAttachImage: widget.controller.canAttachImage,
                  onAddImage: _showImageSourceSheet,
                  onRemoveImage: widget.controller.removeAttachedImage,
                  onSend: _send,
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _CoachHeader extends StatelessWidget {
  const _CoachHeader({
    required this.title,
    required this.onManage,
    required this.onNewConversation,
  });
  final String title;
  final VoidCallback onManage;
  final VoidCallback onNewConversation;

  @override
  Widget build(BuildContext context) {
    final identity = Row(
      children: [
        Container(
          width: 48,
          height: 48,
          decoration: BoxDecoration(
            color: AppColors.darkCard,
            borderRadius: BorderRadius.circular(16),
          ),
          child: const Icon(
            Icons.auto_awesome_rounded,
            color: Colors.white,
            size: 25,
          ),
        ),
        const SizedBox(width: 13),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 3),
              Row(
                children: [
                  Container(
                    width: 7,
                    height: 7,
                    decoration: const BoxDecoration(
                      color: AppColors.mint,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(
                      '训练 · 饮食 · 营养 · 恢复',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
    final actions = Row(
      children: [
        Expanded(
          child: Tooltip(
            message: '新对话',
            child: OutlinedButton.icon(
              onPressed: onNewConversation,
              icon: const Icon(Icons.edit_square, size: 19),
              label: const Text('新建对话'),
            ),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Tooltip(
            message: '历史与记忆',
            child: OutlinedButton.icon(
              onPressed: onManage,
              icon: const Icon(Icons.history_rounded, size: 20),
              label: const Text('历史对话'),
            ),
          ),
        ),
      ],
    );
    return LayoutBuilder(
      builder: (context, constraints) => Container(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 14),
        decoration: const BoxDecoration(
          color: AppColors.canvas,
          border: Border(bottom: BorderSide(color: AppColors.line, width: 0.8)),
        ),
        child: constraints.maxWidth >= 600
            ? Row(
                children: [
                  Expanded(child: identity),
                  const SizedBox(width: 16),
                  SizedBox(width: 280, child: actions),
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [identity, const SizedBox(height: 12), actions],
              ),
      ),
    );
  }
}

class _Welcome extends StatelessWidget {
  const _Welcome({required this.onPrompt});

  final Future<void> Function(String) onPrompt;

  @override
  Widget build(BuildContext context) {
    const prompts = <(IconData, String)>[
      (Icons.bolt_rounded, '今天怎么练？'),
      (Icons.restaurant_rounded, '帮我看看今天怎么吃'),
      (Icons.bedtime_outlined, '最近恢复不好怎么办？'),
    ];
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 30, 20, 24),
      children: [
        Container(
          width: 66,
          height: 66,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: AppColors.primarySoft,
            borderRadius: BorderRadius.circular(22),
          ),
          child: const Icon(
            Icons.auto_awesome_rounded,
            color: AppColors.primary,
            size: 32,
          ),
        ),
        const SizedBox(height: 22),
        Text('今天想解决什么？', style: Theme.of(context).textTheme.headlineLarge),
        const SizedBox(height: 8),
        Text(
          '结合你的资料和记录，为你提供训练安排、饮食建议、营养分析和恢复指导。涉及计划或记录的修改，会先请你确认。',
          style: Theme.of(context).textTheme.bodyLarge
              ?.copyWith(color: AppColors.muted),
        ),
        const SizedBox(height: 26),
        for (final prompt in prompts) ...[
          AppSurface(
            onTap: () => onPrompt(prompt.$2),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
            child: Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: AppColors.indigoSoft,
                    borderRadius: BorderRadius.circular(13),
                  ),
                  child: Icon(prompt.$1, color: AppColors.indigo, size: 21),
                ),
                const SizedBox(width: 13),
                Expanded(
                  child: Text(
                    prompt.$2,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                const Icon(Icons.arrow_forward_rounded, color: AppColors.muted),
              ],
            ),
          ),
          const SizedBox(height: 10),
        ],
      ],
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.message, this.activityLabel});

  final AgentMessage message;
  final String? activityLabel;

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == 'user';
    if (isUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          constraints: const BoxConstraints(maxWidth: 310),
          margin: const EdgeInsets.only(left: 54, bottom: 18),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: AppColors.primarySoft,
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(20),
              topRight: Radius.circular(7),
              bottomLeft: Radius.circular(20),
              bottomRight: Radius.circular(20),
            ),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              if (message.imageAssetIds.isNotEmpty) ...[
                _MessageImages(message: message),
                const SizedBox(height: 8),
              ],
              Text(message.content),
            ],
          ),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 22),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: AppColors.darkCard,
              borderRadius: BorderRadius.circular(11),
            ),
            child: const Icon(
              Icons.auto_awesome_rounded,
              color: Colors.white,
              size: 18,
            ),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (message.content.isEmpty && message.pending)
                  _Thinking(label: activityLabel ?? '正在思考')
                else
                  SelectionArea(
                    child: _AgentReplyText(
                      content: SourceLink.replyText(message.content),
                    ),
                  ),
                if (!message.pending) SourceLinks(content: message.content),
                if (message.pending && message.content.isNotEmpty) ...[
                  const SizedBox(height: 7),
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const _StreamingCursor(),
                      const SizedBox(width: 7),
                      Text(
                        activityLabel ?? '正在回复',
                        style: Theme.of(context).textTheme.labelMedium
                            ?.copyWith(color: AppColors.primary),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _MessageImages extends StatelessWidget {
  const _MessageImages({required this.message});

  final AgentMessage message;

  @override
  Widget build(BuildContext context) {
    final localImages = message.imageAssetIds
        .map((id) => message.localImageBytes[id])
        .whereType<Uint8List>()
        .toList(growable: false);
    if (localImages.isEmpty) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.photo_outlined, size: 18),
          const SizedBox(width: 6),
          Text('已附 ${message.imageAssetIds.length} 张图片'),
        ],
      );
    }
    return Wrap(
      alignment: WrapAlignment.end,
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final bytes in localImages)
          ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: Image.memory(
              bytes,
              width: localImages.length == 1 ? 180 : 86,
              height: localImages.length == 1 ? 135 : 86,
              fit: BoxFit.cover,
              gaplessPlayback: true,
            ),
          ),
      ],
    );
  }
}

class _Thinking extends StatelessWidget {
  const _Thinking({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const SizedBox.square(
          dimension: 16,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
        const SizedBox(width: 9),
        Text(
          label,
          style: Theme.of(context).textTheme.bodyMedium
              ?.copyWith(color: AppColors.muted),
        ),
      ],
    );
  }
}

class _StreamingCursor extends StatefulWidget {
  const _StreamingCursor();

  @override
  State<_StreamingCursor> createState() => _StreamingCursorState();
}

class _StreamingCursorState extends State<_StreamingCursor>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 650),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: Tween<double>(begin: 0.25, end: 1).animate(_controller),
      child: Container(
        width: 2,
        height: 17,
        decoration: BoxDecoration(
          color: AppColors.primary,
          borderRadius: BorderRadius.circular(2),
        ),
      ),
    );
  }
}

class _AgentReplyText extends StatelessWidget {
  const _AgentReplyText({required this.content});

  final String content;

  @override
  Widget build(BuildContext context) {
    final parts = parseAgentReply(content);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 15, 16, 14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.line),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (parts.answer.isNotEmpty) ...[
            _MarkdownLiteText(content: parts.answer),
          ],
          if (parts.analysis.isNotEmpty) ...[
            const SizedBox(height: 10),
            _MarkdownLiteText(content: parts.analysis),
          ],
        ],
      ),
    );
  }
}

class _MarkdownLiteText extends StatelessWidget {
  const _MarkdownLiteText({required this.content});

  final String content;

  @override
  Widget build(BuildContext context) {
    final lines = content.replaceAll('\r\n', '\n').split('\n');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final line in lines)
          if (line.trim().isEmpty)
            const SizedBox(height: 9)
          else if (_isBullet(line))
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 8),
                    child: Icon(Icons.circle, size: 5, color: AppColors.ink),
                  ),
                  const SizedBox(width: 9),
                  Expanded(
                    child: _InlineText(
                      text: line.trimLeft().substring(2).trimRight(),
                    ),
                  ),
                ],
              ),
            )
          else
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: _InlineText(
                text: line.replaceFirst(RegExp(r'^#{1,4}\s*'), ''),
                heading: line.trimLeft().startsWith('#'),
              ),
            ),
      ],
    );
  }

  bool _isBullet(String line) {
    final trimmed = line.trimLeft();
    return trimmed.startsWith('- ') || trimmed.startsWith('* ');
  }
}

class _InlineText extends StatelessWidget {
  const _InlineText({required this.text, this.heading = false});

  final String text;
  final bool heading;

  @override
  Widget build(BuildContext context) {
    final spans = <TextSpan>[];
    final pattern = RegExp(r'\*\*(.+?)\*\*');
    var cursor = 0;
    for (final match in pattern.allMatches(text)) {
      if (match.start > cursor) {
        spans.add(TextSpan(text: text.substring(cursor, match.start)));
      }
      spans.add(
        TextSpan(
          text: match.group(1),
          style: const TextStyle(fontWeight: FontWeight.w700),
        ),
      );
      cursor = match.end;
    }
    if (cursor < text.length) {
      spans.add(TextSpan(text: text.substring(cursor).replaceAll('**', '')));
    }
    return Text.rich(
      TextSpan(
        children: spans.isEmpty
            ? [TextSpan(text: text.replaceAll('**', ''))]
            : spans,
      ),
      style:
          (heading
                  ? Theme.of(context).textTheme.titleMedium
                  : Theme.of(context).textTheme.bodyLarge)
              ?.copyWith(height: 1.55),
    );
  }
}

class _ConfirmationCard extends StatelessWidget {
  const _ConfirmationCard({required this.card, required this.controller});

  final AgentConfirmationCard card;
  final AgentController controller;

  Future<void> _editPortions(BuildContext context) async {
    final preview = card.after?['preview'];
    final entry = card.after?['entry'];
    final items = preview is Map
        ? preview['items']
        : (entry is Map ? entry['items'] : null);
    if (items is! List || items.isEmpty) return;
    final fields = [
      for (final item in items)
        TextEditingController(text: '${(item as Map)['amount_g'] ?? ''}'),
    ];
    final formKey = GlobalKey<FormState>();
    final route = DialogRoute<List<Map<String, Object>>>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('调整这餐份量'),
        content: SingleChildScrollView(
          child: Form(
            key: formKey,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('修改实际克数后会重新计算营养，旧草稿失效，新的仍需确认。'),
                for (var index = 0; index < items.length; index++)
                  TextFormField(
                    controller: fields[index],
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: InputDecoration(
                      labelText:
                          '${(items[index] as Map)['name'] ?? '食物 ${index + 1}'}（克）',
                    ),
                    validator: (value) {
                      final amount = double.tryParse(value ?? '');
                      return amount == null ||
                              !amount.isFinite ||
                              amount <= 0 ||
                              amount > 99999
                          ? '请输入大于 0 的克数'
                          : null;
                    },
                  ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('返回'),
          ),
          FilledButton(
            onPressed: () {
              if (formKey.currentState?.validate() != true) return;
              Navigator.pop(dialogContext, [
                for (var i = 0; i < items.length; i++)
                  {
                    'item_index': i,
                    'amount_g': double.parse(fields[i].text).toStringAsFixed(3),
                  },
              ]);
            },
            child: const Text('重新计算草稿'),
          ),
        ],
      ),
    );
    final result = await Navigator.of(context, rootNavigator: true).push(route);
    // A popped route can still build while its exit animation is running.
    // Release fields only after the overlay has actually removed the route.
    await route.completed;
    for (final field in fields) {
      field.dispose();
    }
    if (result != null) await controller.reviseMealPortions(card, result);
  }

  bool get _isSaved => card.status == 'succeeded';

  String get _savedStatus => switch (card.operationType) {
    'training_plan_activate' || 'nutrition_target_activate' => '已启用',
    'training_plan_archive' => '已归档',
    'food_delete' ||
    'nutrition_entry_delete' ||
    'body_measurement_delete' => '已删除',
    'workout_set_void' || 'workout_record_void' => '已撤销',
    'nutrition_entry_update' ||
    'nutrition_entries_date_change' ||
    'food_update' ||
    'profile_update' ||
    'workout_set_update' ||
    'workout_record_update' ||
    'calendar_reschedule' ||
    'training_progression_apply' => '已更新',
    _ => '已保存',
  };

  String get _title => _isSaved
      ? switch (card.operationType) {
          'nutrition_entry_create' ||
          'nutrition_entry_update' ||
          'nutrition_entry_delete' ||
          'nutrition_entries_date_change' => '饮食记录',
          'food_create' || 'food_update' || 'food_delete' => '自定义食品',
          'profile_update' => '个人资料',
          'water_entry_create' => '饮水记录',
          'body_measurement_create' || 'body_measurement_delete' => '身体记录',
          'training_plan_activate' || 'training_plan_archive' => '训练计划',
          'nutrition_target_activate' => '饮食目标',
          'calendar_reschedule' => '训练日程',
          'training_progression_apply' => '训练强度',
          _ => '训练记录',
        }
      : switch (card.operationType) {
          'training_plan_activate' => '启用训练计划',
          'training_plan_archive' => '归档训练计划',
          'nutrition_entry_create' => '保存这餐饮食',
          'water_entry_create' => '保存饮水记录',
          'nutrition_entry_update' => '更正已保存饮食',
          'nutrition_entries_date_change' => '更正饮食日期',
          'food_create' => '添加自定义食品',
          'food_update' => '修改自定义食品',
          'profile_update' => '修改个人资料',
          'workout_set_update' => '更正训练组记录',
          'workout_set_void' => '作废误记训练组',
          'workout_record_create' => _isWorkoutAppend ? '追加训练动作' : '记录训练动作',
          'workout_record_update' => '更正动作训练记录',
          'workout_record_void' => '撤销误记动作',
          'food_delete' => '删除自定义食品',
          'nutrition_entry_delete' => '删除饮食记录',
          'nutrition_target_activate' => '启用饮食目标',
          'body_measurement_create' => '保存身体记录',
          'body_measurement_delete' => '删除身体记录',
          'calendar_reschedule' => '调整训练日程',
          'training_progression_apply' => '调整训练强度',
          _ => '确认这项更改',
        };

  bool get _isWorkoutAppend {
    final request = card.after?['request'];
    return request is Map && request['workout_id'] != null;
  }

  String get _approveLabel => switch (card.operationType) {
    'training_plan_activate' || 'nutrition_target_activate' => '确认启用',
    'nutrition_entry_create' ||
    'water_entry_create' ||
    'body_measurement_create' => '确认保存',
    'food_create' => '确认添加',
    'food_update' => '确认修改',
    'profile_update' => '确认修改',
    'workout_set_update' => '确认更正',
    'nutrition_entry_update' => '确认更正',
    'nutrition_entries_date_change' => '确认改日期',
    'workout_set_void' => '确认作废',
    'workout_record_create' => '确认记录',
    'workout_record_update' => '确认更正',
    'workout_record_void' => '确认撤销',
    'food_delete' => '确认删除',
    'training_plan_archive' => '确认归档',
    'nutrition_entry_delete' || 'body_measurement_delete' => '确认删除',
    _ => '确认更改',
  };

  String? get _previewTitle {
    if ({
      'food_create',
      'food_update',
      'food_delete',
    }.contains(card.operationType)) {
      final food = card.after?['food'];
      return food is Map ? '${food['name'] ?? '自定义食品'}' : null;
    }
    if (card.operationType == 'training_plan_activate') {
      final name = card.draft?['name'];
      return name is String && name.trim().isNotEmpty ? name.trim() : null;
    }
    if (card.operationType == 'nutrition_entry_create') {
      final entry = card.after?['entry'];
      if (entry is Map) {
        return switch (entry['meal_type']) {
          'breakfast' => '早餐记录',
          'lunch' => '午餐记录',
          'dinner' => '晚餐记录',
          'snack' => '加餐记录',
          _ => '饮食记录',
        };
      }
    }
    return null;
  }

  List<String> _previewFacts(BuildContext context) {
    final units = AppPreferencesScope.unitsOf(context);
    String weightNumber(Object? value) {
      final parsed = double.tryParse('$value');
      return units.imperial && parsed != null
          ? units.weight(parsed).toStringAsFixed(1)
          : '$value';
    }

    String weight(Object? value, [String metricLabel = '公斤']) =>
        '${weightNumber(value)} ${units.imperial ? 'lb' : metricLabel}';
    String length(Object? value, [String metricLabel = '厘米']) {
      final parsed = double.tryParse('$value');
      return units.imperial && parsed != null
          ? units.formatLength(parsed)
          : '$value $metricLabel';
    }

    if (card.operationType == 'water_entry_create') {
      final water = card.after?['water'];
      if (water is! Map) return [card.impact];
      final date = DateTime.tryParse('${water['consumed_at']}')
          ?.toUtc()
          .add(const Duration(hours: 8));
      return [
        '饮水 ${water['amount_ml']} ml',
        if (date != null) '${date.year}年${date.month}月${date.day}日',
      ];
    }
    if (card.operationType == 'workout_record_create') {
      final preview = card.after?['preview'];
      final request = card.after?['request'];
      final facts = preview is Map ? preview : request;
      if (facts is! Map) return [card.impact];
      return [
        '${facts['date'] ?? facts['workout_date'] ?? '日期待核对'} · ${facts['exercise_name'] ?? '动作待核对'}',
        '${weight(facts['weight_kg'] ?? '重量待核对')} · ${facts['sets'] ?? '组数待核对'} 组 · 每组 ${facts['reps'] ?? '次数待核对'} 次',
        if (request is Map && request['workout_id'] != null)
          '追加到原训练，保留已记录的其他动作',
        if (!_isSaved) '确认后保存实际训练组；训练保持进行中，结束时请在训练页完成训练',
      ];
    }
    if (card.operationType == 'workout_record_update' ||
        card.operationType == 'workout_record_void') {
      final preview = card.after?['preview'];
      if (preview is! Map) return [card.impact];
      final old = preview['before_sets'];
      final next = preview['after_sets'];
      final isVoid = card.operationType == 'workout_record_void';
      final previousSets = old is List
          ? old.whereType<Map>().toList()
          : <Map>[];
      final nextSets = next is List ? next.whereType<Map>().toList() : <Map>[];
      return [
        '${preview['date']} · ${preview['exercise_name']} · ${previousSets.length} 组${!isVoid && previousSets.length != nextSets.length ? ' → ${nextSets.length} 组' : ''}',
        for (final before in previousSets)
          if (isVoid)
            '撤销第 ${before['set_index']} 组：${weight(before['weight_kg'])} × ${before['reps']} 次'
          else ...[
            if (!nextSets.any((after) => after['set_id'] == before['set_id']))
              '作废第 ${before['set_index']} 组：${weight(before['weight_kg'])} × ${before['reps']} 次',
            for (final after in nextSets)
              if (after['set_id'] == before['set_id'])
                '第 ${before['set_index']} 组：${weight(before['weight_kg'])} × ${before['reps']} 次 → ${weight(after['weight_kg'])} × ${after['reps']} 次',
          ],
        for (final after in nextSets)
          if (after['added'] == true)
            '新增第 ${after['set_index']} 组：${weight(after['weight_kg'])} × ${after['reps']} 次',
        if (isVoid && !_isSaved) '确认后该动作的这些组不再计入有效训练，原记录和修订历史保留',
        '仅修改所列训练组，保留这次训练的其他动作和已有训练计划',
      ];
    }
    if (card.operationType == 'nutrition_entries_date_change') {
      final preview = card.after?['preview'];
      if (preview is! Map) return [card.impact];
      final entries = preview['entries'];
      const mealNames = {
        'breakfast': '早餐',
        'lunch': '午餐',
        'dinner': '晚餐',
        'snack': '加餐',
        'other': '餐食',
      };
      return [
        '日期：${preview['source_date']} → ${preview['target_date']}',
        if (entries is List)
          for (final entry in entries.whereType<Map>())
            '${entry['time']} · ${mealNames[entry['meal_type']] ?? '餐食'} · '
                '${entry['foods'] is List ? (entry['foods'] as List).join('、') : '餐食'}'
                '${entry['kcal'] != null ? ' · ${entry['kcal']} 千卡' : ''}',
        if (!_isSaved) '确认后移动所列原记录，保留用餐时间、食物、营养和备注',
        '两天的饮食统计会更新，目标日期已有餐食保留',
      ];
    }
    if (card.operationType == 'nutrition_entry_update' ||
        card.operationType == 'nutrition_entry_delete') {
      final preview = card.after?['preview'];
      if (preview is! Map) return [card.impact];
      final meal = switch (preview['meal_type']) {
        'breakfast' => '早餐',
        'lunch' => '午餐',
        'dinner' => '晚餐',
        'snack' => '加餐',
        _ => '餐食',
      };
      final before = preview['totals_before'];
      final after = preview['totals_after'];
      final changes = preview['changes'];
      final removedItems = preview['removed_items'];
      final clock =
          RegExp(r'[T ](\d{2}:\d{2})')
              .firstMatch('${preview['eaten_at']}')
              ?.group(1) ??
          '时间待核对';
      return [
        '${preview['date']} · $meal · $clock',
        if (changes is List)
          for (final change in changes)
            if (change is Map) ...[
              change['replacement_name'] != null
                  ? '${change['name']} → ${change['replacement_name']}（${change['amount_g']} 克）'
                  : '${change['name']}：${change['old_amount_g']} 克 → ${change['amount_g']} 克',
              if (change['estimate_assumptions'] is String)
                '重新估算依据：${change['estimate_assumptions']}',
            ],
        if (removedItems is List)
          for (final item in removedItems)
            if (item is Map)
              '移除 ${item['name']}（${item['amount_g']} 克），保留这餐其他食物',
        if (card.operationType == 'nutrition_entry_delete')
          if (!_isSaved) '确认后仅将这一餐从统计中移除，原记录和修订保留',
        if (before is Map && after is Map) ...[
          '这餐热量：${before['kcal']} → ${after['kcal']} 千卡',
          '蛋白质：${before['protein_g']} → ${after['protein_g']} 克',
          '碳水：${before['carbs_g']} → ${after['carbs_g']} 克',
          '脂肪：${before['fat_g']} → ${after['fat_g']} 克',
        ],
        if (card.operationType == 'nutrition_entry_update')
          changes is List &&
                  changes.whereType<Map>().any(
                    (item) => item['replacement_name'] != null,
                  )
              ? '替换项按新食物依据估算，其他食物保持原样'
              : changes is List &&
                    changes.whereType<Map>().any(
                      (item) => item['nutrition_after'] is Map,
                    )
              ? '所列食物采用新的暂定估算，其他食物保持原样'
              : '沿用原营养依据，其他食物保持原样',
        if (!_isSaved) '确认后更新饮食统计，食品库和其他餐食不变',
      ];
    }
    if (card.operationType == 'workout_set_update' ||
        card.operationType == 'workout_set_void') {
      final preview = card.after?['preview'];
      if (preview is! Map) return [card.impact];
      final old = preview['before_set'];
      final next = preview['after_set'];
      return [
        '${preview['date']} · ${preview['exercise_name']} · 第 ${preview['set_index']} 组',
        if (old is Map) '原记录：${weight(old['weight_kg'])} × ${old['reps']} 次',
        if (next is Map) '更正为：${weight(next['weight_kg'])} × ${next['reps']} 次',
        if (card.operationType == 'workout_set_void' && !_isSaved)
          '确认后此组不再计入有效训练，其他组保留',
        '本次记录训练量：${weightNumber(preview['volume_before'])} → ${weight(preview['volume_after'])}·次',
        '保留修订历史，已有训练计划不变',
      ];
    }
    if (card.operationType == 'profile_update') {
      final changes = card.after?['changes'];
      final old = card.before?['profile'];
      if (changes is! Map || old is! Map) return [card.impact];
      const labels = {
        'display_name': '昵称',
        'sex': '性别',
        'birth_date': '出生日期',
        'height_cm': '身高',
        'weight_kg': '体重',
        'experience_level': '训练经验',
        'weekly_training_days': '每周训练天数',
        'session_duration_minutes': '单次训练时长',
      };
      String display(String field, Object? value) {
        if (value == null) return '未填写';
        if (field == 'weight_kg') return weight(value);
        if (field == 'height_cm') return length(value);
        const translated = {
          'male': '男',
          'female': '女',
          'other': '其他',
          'unspecified': '未填写',
          'beginner': '新手',
          'intermediate': '有一定经验',
          'advanced': '经验丰富',
        };
        final text = (field == 'sex' || field == 'experience_level')
            ? translated[value.toString()] ?? value.toString()
            : value.toString();
        final unit = switch (field) {
          'height_cm' => ' 厘米',
          'weight_kg' => ' 公斤',
          'weekly_training_days' => ' 天',
          'session_duration_minutes' => ' 分钟',
          _ => '',
        };
        return '$text$unit';
      }

      return [
        for (final field in labels.keys)
          if (changes.containsKey(field))
            '${labels[field]}：${display(field, old[field])} → ${display(field, changes[field])}',
        if (changes.containsKey('weight_kg')) '体重会新增当前测量，历史记录保留',
      ];
    }
    if ({
      'food_create',
      'food_update',
      'food_delete',
    }.contains(card.operationType)) {
      final food = card.after?['food'];
      if (food is! Map) return [card.impact];
      final old = card.before?['food'];
      return [
        if (card.operationType == 'food_update' && old is Map) ...[
          '原：${old['name']}，每 ${old['basis_amount_g']} 克 ${old['kcal']} 千卡',
          '原蛋白质 ${old['protein_g']} 克 · 碳水 ${old['carbs_g']} 克 · 脂肪 ${old['fat_g']} 克',
          if (old['brand'] != food['brand'])
            '品牌：${old['brand'] ?? '未填写'} → ${food['brand'] ?? '未填写'}',
          if (old['barcode'] != food['barcode'])
            '条码：${old['barcode'] ?? '未填写'} → ${food['barcode'] ?? '未填写'}',
          '新：${food['name']}',
        ],
        if (food['brand'] is String) '品牌：${food['brand']}',
        if (food['barcode'] is String) '条码：${food['barcode']}',
        '每 ${food['basis_amount_g']} 克：${food['kcal']} 千卡',
        '蛋白质 ${food['protein_g']} 克 · 碳水 ${food['carbs_g']} 克 · 脂肪 ${food['fat_g']} 克',
        if (food['source'] == 'model_estimated')
          _isSaved ? '按常见配方估算' : '暂定估算，确认前请核对份量和营养',
        if (food['notes'] is String) food['notes'] as String,
        if (card.operationType == 'food_delete' && !_isSaved)
          '确认后仅移除食品库条目，已保存的饮食和营养统计保留',
      ];
    }
    if (card.operationType == 'calendar_reschedule') {
      final before = card.draft?['before_events'];
      final after = card.draft?['after_events'];
      return [
        if (before is List)
          ...before.whereType<Map>().map(
            (event) => '原安排：${event['scheduled_date']} ${event['title']}',
          ),
        if (after is List)
          ...after.whereType<Map>().map(
            (event) => event['status'] == 'skipped'
                ? '拟跳过：${event['title']}'
                : '拟安排：${event['scheduled_date']} ${event['title']}',
          ),
        if (card.draft?['strategy'] == 'compression') ...[
          '本次时长变化：${card.draft?['duration_change_minutes']} 分钟',
          '估计训练量变化：${card.draft?['volume_change_percent']}%',
          if (before is List &&
              before.isNotEmpty &&
              after is List &&
              after.isNotEmpty)
            '时长：${(before.first as Map)['estimated_minutes']} → ${(after.first as Map)['estimated_minutes']} 分钟',
        ],
      ];
    }
    if (card.operationType == 'training_progression_apply') {
      final suggestions = card.draft?['suggestions'];
      if (suggestions is List) {
        return suggestions
            .whereType<Map>()
            .expand((item) {
              final current = item['current_target'];
              final proposed = item['proposed_target'];
              return <String>[
                if (current is Map && proposed is Map)
                  '${item['exercise_name'] ?? "动作"}：${weightNumber(current['weight_kg'])} → ${weight(proposed['weight_kg'])}',
                if (item['evidence'] is List)
                  ...(item['evidence'] as List).whereType<String>(),
                if (item['warnings'] is List)
                  ...(item['warnings'] as List).whereType<String>(),
              ];
            })
            .toList(growable: false);
      }
    }
    if (card.operationType == 'training_plan_activate') {
      final draft = card.draft;
      final facts = <String>[];
      final frequency = draft?['weekly_frequency'];
      if (frequency is int) facts.add('每周 $frequency 次');
      final days = draft?['days'];
      if (days is List) {
        final names = days
            .whereType<Map>()
            .map((day) => day['name'])
            .whereType<String>()
            .where((name) => name.trim().isNotEmpty)
            .take(3)
            .toList(growable: false);
        if (names.isNotEmpty) facts.add('训练日：${names.join(' · ')}');
      }
      return facts;
    }
    if (card.operationType == 'body_measurement_create') {
      final measurement = card.after?['measurement'];
      if (measurement is! Map) return const [];
      return [
        if (measurement['weight_kg'] != null)
          '体重 ${weight(measurement['weight_kg'], 'kg')}',
        if (measurement['waist_cm'] != null)
          '腰围 ${length(measurement['waist_cm'], 'cm')}',
        if (measurement['body_fat_percent'] != null)
          '体脂 ${measurement['body_fat_percent']}%',
      ];
    }
    if (card.operationType == 'nutrition_entry_create') {
      final draft = card.draft;
      final preview = card.after?['preview'];
      final items =
          draft?['items'] ?? (preview is Map ? preview['items'] : null);
      final totals =
          draft?['totals'] ?? (preview is Map ? preview['totals'] : null);
      if (items is List) {
        return [
          ...items.whereType<Map>().map((item) {
            final name = item['name'] ?? '食品';
            final amount = item['amount_g'];
            final estimate = item['source'] == 'model_estimated'
                ? '（暂定估算）'
                : '';
            return '$name ${amount ?? "待核对"} 克$estimate';
          }),
          if (totals is Map)
            '合计约 ${totals['kcal']} 千卡，蛋白质 ${totals['protein_g']} 克',
          if (totals is Map)
            '碳水 ${totals['carbs_g']} 克 · 脂肪 ${totals['fat_g']} 克',
          for (final item in items.whereType<Map>())
            if (item['estimate_assumptions'] is String)
              '${item['name']}重估依据：${item['estimate_assumptions']}',
          if (draft?['notes'] is String) draft!['notes'] as String,
        ];
      }
      final entry = card.after?['entry'];
      if (entry is Map && entry['items'] is List) {
        return ['${(entry['items'] as List).length} 种食物'];
      }
    }
    if (card.operationType == 'nutrition_target_activate') {
      final values = card.draft?['values'];
      if (values is Map) {
        return [
          '热量 ${values['kcal_min']}–${values['kcal_max']} 千卡',
          '蛋白质 ${values['protein_min_g']}–${values['protein_max_g']} 克',
          '碳水 ${values['carbs_min_g']}–${values['carbs_max_g']} 克',
          '脂肪 ${values['fat_min_g']}–${values['fat_max_g']} 克',
        ];
      }
    }
    return const [];
  }

  String get _impactText {
    if (card.operationType == 'body_measurement_create') {
      return '确认后会记入身体数据，方便查看进度变化。';
    }
    return card.impact;
  }

  @override
  Widget build(BuildContext context) {
    final previewTitle = _previewTitle;
    final previewFacts = _previewFacts(context);
    return Padding(
      padding: const EdgeInsets.only(left: 45, bottom: 16),
      child: AppSurface(
        borderColor: (_isSaved ? AppColors.mint : AppColors.amber).withValues(
          alpha: 0.4,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(
                    color: _isSaved
                        ? AppColors.mint.withValues(alpha: 0.12)
                        : AppColors.amberSoft,
                    borderRadius: BorderRadius.circular(11),
                  ),
                  child: Icon(
                    _isSaved
                        ? Icons.check_circle_outline
                        : Icons.fact_check_outlined,
                    color: _isSaved ? AppColors.mint : AppColors.amber,
                    size: 21,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    _title,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                if (_isSaved)
                  Text(
                    _savedStatus,
                    style: Theme.of(context).textTheme.labelMedium
                        ?.copyWith(color: AppColors.mint),
                  ),
              ],
            ),
            if (previewTitle != null || previewFacts.isNotEmpty) ...[
              const SizedBox(height: 13),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AppColors.canvas,
                  borderRadius: BorderRadius.circular(13),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (previewTitle != null)
                      Text(
                        previewTitle,
                        style: Theme.of(context).textTheme.labelLarge,
                      ),
                    for (final fact in previewFacts) ...[
                      const SizedBox(height: 4),
                      Text(fact, style: Theme.of(context).textTheme.bodyMedium),
                    ],
                    if (card.operationType == 'training_plan_activate' &&
                        card.draft?['days'] is List)
                      _TrainingDraftPreview(days: card.draft!['days'] as List),
                  ],
                ),
              ),
            ],
            if (!_isSaved) ...[
              const SizedBox(height: 12),
              Text(
                _impactText,
                style: Theme.of(context).textTheme.bodyMedium
                    ?.copyWith(color: AppColors.muted),
              ),
              const SizedBox(height: 5),
              Text(
                '只有你确认后才会生效',
                style: Theme.of(context).textTheme.labelMedium
                    ?.copyWith(color: AppColors.amber),
              ),
              const SizedBox(height: 14),
              if (card.operationType == 'nutrition_entry_create')
                TextButton.icon(
                  onPressed: controller.sending || controller.isDeciding(card)
                      ? null
                      : () => _editPortions(context),
                  icon: const Icon(Icons.edit_outlined),
                  label: const Text('调整份量'),
                ),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed:
                          controller.sending || controller.isDeciding(card)
                          ? null
                          : () => controller.decide(card, approve: false),
                      child: const Text('取消'),
                    ),
                  ),
                  const SizedBox(width: 9),
                  Expanded(
                    child: FilledButton(
                      onPressed:
                          controller.sending || controller.isDeciding(card)
                          ? null
                          : () => controller.decide(card, approve: true),
                      child: Text(_approveLabel),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _TrainingDraftPreview extends StatelessWidget {
  const _TrainingDraftPreview({required this.days});

  final List days;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.canvas,
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: 6),
        title: const Text('查看各训练日和动作'),
        children: [
          for (var index = 0; index < days.length; index++)
            if (days[index] is Map)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: _day(context, days[index] as Map, index + 1),
              ),
        ],
      ),
    );
  }

  Widget _day(BuildContext context, Map day, int index) {
    final exercises = day['exercises'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '第 $index 天 · ${day['name'] ?? '训练日'}',
          style: Theme.of(context).textTheme.labelLarge,
        ),
        const SizedBox(height: 3),
        Text('约 ${day['estimated_minutes'] ?? '—'} 分钟'),
        if (exercises is List)
          for (final exercise in exercises)
            if (exercise is Map)
              Padding(
                padding: const EdgeInsets.only(top: 5),
                child: Text(_exerciseText(exercise)),
              ),
      ],
    );
  }

  String _exerciseText(Map exercise) {
    final name = exercise['exercise_name'] ?? '动作名称暂不可用';
    final sets = exercise['target_sets'];
    final min = exercise['rep_min'];
    final max = exercise['rep_max'];
    final reps = min == max ? '$min' : '$min–$max';
    final target = sets != null && min != null && max != null
        ? ' · $sets 组 × $reps 次'
        : '';
    final reserve = exercise['target_rir'];
    return '$name$target${reserve == null ? '' : ' · 做完还能再做约 $reserve 次'}';
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.focusNode,
    required this.sending,
    required this.uploadingImage,
    required this.attachedImages,
    required this.pendingImageBytes,
    required this.canAttachImage,
    required this.onAddImage,
    required this.onRemoveImage,
    required this.onSend,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool sending;
  final bool uploadingImage;
  final List<UploadedImage> attachedImages;
  final List<Uint8List> pendingImageBytes;
  final bool canAttachImage;
  final VoidCallback onAddImage;
  final ValueChanged<String> onRemoveImage;
  final Future<void> Function([String?]) onSend;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.fromLTRB(
        14,
        10,
        14,
        MediaQuery.paddingOf(context).bottom + 10,
      ),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: AppColors.line, width: 0.8)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (attachedImages.isNotEmpty || pendingImageBytes.isNotEmpty) ...[
            SizedBox(
              height: 70,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: attachedImages.length + pendingImageBytes.length,
                separatorBuilder: (_, _) => const SizedBox(width: 8),
                itemBuilder: (context, index) {
                  final pending = index >= attachedImages.length;
                  final image = pending ? null : attachedImages[index];
                  final bytes = pending
                      ? pendingImageBytes[index - attachedImages.length]
                      : image!.bytes;
                  return Stack(
                    clipBehavior: Clip.none,
                    children: [
                      ClipRRect(
                        borderRadius: BorderRadius.circular(12),
                        child: Image.memory(
                          bytes,
                          width: 70,
                          height: 70,
                          fit: BoxFit.cover,
                          gaplessPlayback: true,
                        ),
                      ),
                      if (pending)
                        Positioned.fill(
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              color: Colors.black.withValues(alpha: 0.24),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: const Center(
                              child: SizedBox.square(
                                dimension: 22,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2.5,
                                  color: Colors.white,
                                ),
                              ),
                            ),
                          ),
                        )
                      else
                        Positioned(
                          top: -5,
                          right: -5,
                          child: InkWell(
                            onTap: () => onRemoveImage(image!.assetId),
                            borderRadius: BorderRadius.circular(20),
                            child: Container(
                              padding: const EdgeInsets.all(3),
                              decoration: const BoxDecoration(
                                color: AppColors.ink,
                                shape: BoxShape.circle,
                              ),
                              child: const Icon(
                                Icons.close_rounded,
                                size: 15,
                                color: Colors.white,
                              ),
                            ),
                          ),
                        ),
                    ],
                  );
                },
              ),
            ),
            const SizedBox(height: 9),
          ],
          if (uploadingImage) ...[
            const LinearProgressIndicator(minHeight: 2),
            const SizedBox(height: 6),
            Text(
              '图片已显示，正在安全上传…',
              style: Theme.of(context).textTheme.labelMedium,
            ),
            const SizedBox(height: 8),
          ],
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              IconButton.outlined(
                tooltip: attachedImages.length + pendingImageBytes.length >= 4
                    ? '最多添加 4 张图片'
                    : '添加照片',
                onPressed: canAttachImage ? onAddImage : null,
                icon: const Icon(Icons.add_photo_alternate_outlined),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                  controller: controller,
                  focusNode: focusNode,
                  minLines: 1,
                  maxLines: 5,
                  textInputAction: TextInputAction.newline,
                  decoration: const InputDecoration(
                    hintText: '问问题或添加照片…',
                    contentPadding: EdgeInsets.symmetric(
                      horizontal: 17,
                      vertical: 13,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 9),
              IconButton.filled(
                tooltip: '发送',
                onPressed: sending || uploadingImage ? null : () => onSend(),
                padding: const EdgeInsets.all(14),
                icon: sending
                    ? const SizedBox.square(
                        dimension: 19,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(Icons.arrow_upward_rounded),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

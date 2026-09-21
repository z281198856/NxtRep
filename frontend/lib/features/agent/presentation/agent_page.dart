import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/media/image_upload.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/agent_models.dart';
import 'agent_controller.dart';

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

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_scheduleScrollToEnd);
    _scroll.addListener(_trackScrollPosition);
    unawaited(_recoverLostImages());
  }

  @override
  void dispose() {
    widget.controller.removeListener(_scheduleScrollToEnd);
    _scroll.removeListener(_trackScrollPosition);
    _scrollThrottle?.cancel();
    _input.dispose();
    _focusNode.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _trackScrollPosition() {
    if (!_scroll.hasClients) return;
    _followTail =
        _scroll.position.maxScrollExtent - _scroll.position.pixels < 120;
  }

  void _scheduleScrollToEnd() {
    if (!_followTail || _scrollThrottle?.isActive == true) return;
    _scrollThrottle = Timer(const Duration(milliseconds: 70), () {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || !_scroll.hasClients || !_followTail) return;
        _scroll.jumpTo(_scroll.position.maxScrollExtent);
      });
    });
  }

  Future<void> _send([String? suggested]) async {
    final text = suggested ?? _input.text;
    if ((text.trim().isEmpty && widget.controller.attachedImages.isEmpty) ||
        widget.controller.sending ||
        widget.controller.uploadingImage) {
      return;
    }
    _input.clear();
    _focusNode.unfocus();
    _followTail = true;
    await widget.controller.send(text);
  }

  Future<void> _recoverLostImages() async {
    try {
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
                '发送照片给 AI 教练',
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) => Column(
            children: [
              const _CoachHeader(),
              Expanded(
                child: widget.controller.messages.isEmpty
                    ? _Welcome(onPrompt: _send)
                    : NotificationListener<ScrollNotification>(
                        onNotification: (_) {
                          _trackScrollPosition();
                          return false;
                        },
                        child: ListView.builder(
                          controller: _scroll,
                          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                          itemCount:
                              widget.controller.messages.length +
                              widget.controller.confirmations.length,
                          itemBuilder: (context, index) {
                            if (index < widget.controller.messages.length) {
                              final message = widget.controller.messages[index];
                              return _MessageBubble(
                                message: message,
                                activityLabel:
                                    index ==
                                        widget.controller.messages.length - 1
                                    ? widget.controller.activityLabel
                                    : null,
                              );
                            }
                            return _ConfirmationCard(
                              card:
                                  widget.controller.confirmations[index -
                                      widget.controller.messages.length],
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
                    avatar: const Icon(Icons.arrow_downward_rounded, size: 17),
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
          ),
        ),
      ),
    );
  }
}

class _CoachHeader extends StatelessWidget {
  const _CoachHeader();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 14),
      decoration: const BoxDecoration(
        color: AppColors.canvas,
        border: Border(bottom: BorderSide(color: AppColors.line, width: 0.8)),
      ),
      child: Row(
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
                Text('AI 教练', style: Theme.of(context).textTheme.titleLarge),
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
                    Text(
                      '在线 · 建议仅供运动参考',
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
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
          '我会结合你的目标、训练安排和已有记录给出建议。涉及修改时，会先让你确认。',
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
                    child: _MarkdownLiteText(content: message.content),
                  ),
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
              ?.copyWith(height: 1.62),
    );
  }
}

class _ConfirmationCard extends StatelessWidget {
  const _ConfirmationCard({required this.card, required this.controller});

  final AgentConfirmationCard card;
  final AgentController controller;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 45, bottom: 16),
      child: AppSurface(
        color: AppColors.amberSoft,
        borderColor: AppColors.amber.withValues(alpha: 0.22),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(Icons.fact_check_outlined, color: AppColors.amber),
                const SizedBox(width: 8),
                Text('执行前需要确认', style: Theme.of(context).textTheme.titleMedium),
              ],
            ),
            const SizedBox(height: 9),
            Text(card.impact),
            const SizedBox(height: 15),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => controller.decide(card, approve: false),
                    child: const Text('暂不执行'),
                  ),
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: FilledButton(
                    onPressed: () => controller.decide(card, approve: true),
                    child: const Text('确认执行'),
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

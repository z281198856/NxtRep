import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/body_progress_models.dart';
import 'body_progress_controller.dart';

class BodyProgressPage extends StatefulWidget {
  const BodyProgressPage({super.key, required this.controller});

  final BodyProgressController controller;

  @override
  State<BodyProgressPage> createState() => _BodyProgressPageState();
}

class _BodyProgressPageState extends State<BodyProgressPage> {
  final _picker = ImagePicker();

  @override
  void initState() {
    super.initState();
    widget.controller.refresh();
  }

  Future<void> _chooseSource() async {
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 22),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('添加进度照片', style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text(
                '建议在相同光线、距离和姿势下拍摄，便于后续对比。',
                style: Theme.of(context).textTheme.bodyMedium
                    ?.copyWith(color: AppColors.muted),
              ),
              const SizedBox(height: 18),
              FilledButton.icon(
                onPressed: () => Navigator.pop(context, ImageSource.camera),
                icon: const Icon(Icons.photo_camera_rounded),
                label: const Text('现在拍摄'),
              ),
              const SizedBox(height: 10),
              OutlinedButton.icon(
                onPressed: () => Navigator.pop(context, ImageSource.gallery),
                icon: const Icon(Icons.photo_library_outlined),
                label: const Text('从相册选择'),
              ),
            ],
          ),
        ),
      ),
    );
    if (source == null || !mounted) return;
    final picked = await _picker.pickImage(
      source: source,
      maxWidth: 1440,
      maxHeight: 1440,
      imageQuality: 80,
      requestFullMetadata: false,
    );
    if (picked == null || !mounted) return;
    final bytes = await picked.readAsBytes();
    if (!mounted) return;
    final draft = await showModalBottomSheet<_PhotoDraft>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _PhotoDetailsSheet(bytes: bytes),
    );
    if (draft == null || !mounted) return;
    final saved = await widget.controller.addPhoto(
      bytes: draft.bytes,
      view: draft.view,
      capturedAt: draft.capturedAt,
      notes: draft.notes,
    );
    if (!mounted || !saved) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('进度照片已保存')));
  }

  Future<void> _compare() async {
    final photos = widget.controller.photos;
    if (photos.length < 2) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('至少需要两张照片才能进行对比')));
      return;
    }
    final selection =
        await showModalBottomSheet<(BodyProgressPhoto, BodyProgressPhoto)>(
          context: context,
          isScrollControlled: true,
          useSafeArea: true,
          builder: (_) => _CompareSheet(photos: photos),
        );
    if (selection == null || !mounted) return;
    final result = await widget.controller.compare(selection.$1, selection.$2);
    if (result == null || !mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => _AssessmentPage(title: '照片对比结果', assessment: result),
      ),
    );
  }

  Future<void> _generateReport() async {
    final report = await widget.controller.generateReport();
    if (report == null || !mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => _ReportPage(report: report)),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('身体进度')),
      body: SafeArea(
        top: false,
        child: ListenableBuilder(
          listenable: widget.controller,
          builder: (context, _) {
            final controller = widget.controller;
            return RefreshIndicator(
              onRefresh: controller.refresh,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(20, 8, 20, 34),
                children: [
                  Text(
                    '用同样的角度记录真实变化',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 7),
                  Text(
                    '照片默认保存在你的私有空间；AI 只描述可观察信息，不做医学诊断。',
                    style: Theme.of(context).textTheme.bodyMedium
                        ?.copyWith(color: AppColors.muted),
                  ),
                  if (controller.errorMessage case final message?) ...[
                    const SizedBox(height: 14),
                    AppErrorCard(message: message),
                  ],
                  const SizedBox(height: 18),
                  _ActionPanel(
                    uploading: controller.uploading,
                    analyzing: controller.analyzingPhotoId != null,
                    onAdd: _chooseSource,
                    onCompare: _compare,
                  ),
                  const SizedBox(height: 26),
                  SectionTitle(
                    title: '阶段报告',
                    action: TextButton(
                      onPressed: controller.generatingReport
                          ? null
                          : _generateReport,
                      child: Text(
                        controller.generatingReport ? '生成中…' : '生成 30 天报告',
                      ),
                    ),
                  ),
                  const SizedBox(height: 10),
                  _ReportPreview(
                    report: controller.reports.firstOrNull,
                    loading: controller.generatingReport,
                    onTap: controller.reports.isEmpty
                        ? _generateReport
                        : () => Navigator.of(context).push(
                            MaterialPageRoute<void>(
                              builder: (_) =>
                                  _ReportPage(report: controller.reports.first),
                            ),
                          ),
                  ),
                  const SizedBox(height: 26),
                  const SectionTitle(title: '照片记录'),
                  const SizedBox(height: 10),
                  if (controller.loading && controller.photos.isEmpty)
                    const AppSurface(
                      child: SizedBox(
                        height: 170,
                        child: Center(child: CircularProgressIndicator()),
                      ),
                    )
                  else if (controller.photos.isEmpty)
                    AppEmptyState(
                      icon: Icons.add_a_photo_outlined,
                      title: '还没有进度照片',
                      message: '先添加一张正面、侧面或背面照片，之后可进行 AI 评估和前后对比。',
                      action: FilledButton.icon(
                        onPressed: _chooseSource,
                        icon: const Icon(Icons.add_a_photo_rounded),
                        label: const Text('添加第一张照片'),
                      ),
                    )
                  else
                    GridView.builder(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      gridDelegate:
                          const SliverGridDelegateWithFixedCrossAxisCount(
                            crossAxisCount: 2,
                            crossAxisSpacing: 12,
                            mainAxisSpacing: 12,
                            childAspectRatio: 0.72,
                          ),
                      itemCount: controller.photos.length,
                      itemBuilder: (context, index) {
                        final photo = controller.photos[index];
                        return _PhotoCard(
                          controller: controller,
                          photo: photo,
                          onTap: () => Navigator.of(context).push(
                            MaterialPageRoute<void>(
                              builder: (_) => _PhotoDetailPage(
                                controller: controller,
                                photoId: photo.id,
                              ),
                            ),
                          ),
                        );
                      },
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

class _ActionPanel extends StatelessWidget {
  const _ActionPanel({
    required this.uploading,
    required this.analyzing,
    required this.onAdd,
    required this.onCompare,
  });

  final bool uploading;
  final bool analyzing;
  final VoidCallback onAdd;
  final VoidCallback onCompare;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      color: AppColors.darkCard,
      borderColor: AppColors.darkCard,
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(
            Icons.center_focus_strong_rounded,
            color: Colors.white,
            size: 30,
          ),
          const SizedBox(height: 14),
          Text(
            '建立可比较的身体档案',
            style: Theme.of(context).textTheme.titleLarge
                ?.copyWith(color: Colors.white),
          ),
          const SizedBox(height: 5),
          Text(
            '建议每 2–4 周、同一时段记录一次。',
            style: Theme.of(context).textTheme.bodyMedium
                ?.copyWith(color: Colors.white60),
          ),
          const SizedBox(height: 18),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: uploading ? null : onAdd,
                  icon: uploading
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.add_a_photo_rounded),
                  label: Text(uploading ? '上传处理中…' : '添加照片'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.white,
                    side: const BorderSide(color: Colors.white24),
                  ),
                  onPressed: analyzing ? null : onCompare,
                  icon: const Icon(Icons.compare_rounded),
                  label: const Text('前后对比'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PhotoCard extends StatelessWidget {
  const _PhotoCard({
    required this.controller,
    required this.photo,
    required this.onTap,
  });

  final BodyProgressController controller;
  final BodyProgressPhoto photo;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    if (!controller.localPreviews.containsKey(photo.imageAssetId) &&
        !controller.downloads.containsKey(photo.imageAssetId) &&
        !controller.loadingImages.contains(photo.imageAssetId)) {
      Future.microtask(() => controller.ensureDownload(photo));
    }
    return AppSurface(
      onTap: onTap,
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: _PhotoImage(controller: controller, photo: photo),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 11, 12, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        photo.view.label,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                    ),
                    if (photo.assessment != null)
                      const Icon(
                        Icons.auto_awesome_rounded,
                        color: AppColors.primary,
                        size: 18,
                      ),
                  ],
                ),
                const SizedBox(height: 3),
                Text(
                  _date(photo.capturedAt),
                  style: Theme.of(context).textTheme.labelMedium,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PhotoImage extends StatelessWidget {
  const _PhotoImage({required this.controller, required this.photo});

  final BodyProgressController controller;
  final BodyProgressPhoto photo;

  @override
  Widget build(BuildContext context) {
    final bytes = controller.localPreviews[photo.imageAssetId];
    final intent = controller.downloads[photo.imageAssetId];
    Widget child;
    if (bytes != null) {
      child = Image.memory(bytes, fit: BoxFit.cover, gaplessPlayback: true);
    } else if (intent != null) {
      child = Image.network(
        intent.url,
        headers: intent.headers,
        fit: BoxFit.cover,
        gaplessPlayback: true,
        errorBuilder: (_, _, _) =>
            const _ImagePlaceholder(icon: Icons.broken_image_outlined),
      );
    } else {
      child = const _ImagePlaceholder(
        icon: Icons.photo_outlined,
        loading: true,
      );
    }
    return ColoredBox(color: AppColors.canvas, child: child);
  }
}

class _ImagePlaceholder extends StatelessWidget {
  const _ImagePlaceholder({required this.icon, this.loading = false});
  final IconData icon;
  final bool loading;

  @override
  Widget build(BuildContext context) => Center(
    child: loading
        ? const CircularProgressIndicator(strokeWidth: 2)
        : Icon(icon, color: AppColors.muted),
  );
}

class _PhotoDetailPage extends StatelessWidget {
  const _PhotoDetailPage({required this.controller, required this.photoId});

  final BodyProgressController controller;
  final String photoId;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final photo = controller.photos.firstWhere(
          (item) => item.id == photoId,
        );
        final assessment = photo.assessment;
        return Scaffold(
          appBar: AppBar(title: Text('${photo.view.label}进度照')),
          body: ListView(
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 34),
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(24),
                child: AspectRatio(
                  aspectRatio: 0.78,
                  child: _PhotoImage(controller: controller, photo: photo),
                ),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  StatusPill(
                    label: photo.view.label,
                    color: AppColors.indigo,
                    icon: Icons.accessibility_new_rounded,
                  ),
                  const Spacer(),
                  Text(
                    _date(photo.capturedAt),
                    style: Theme.of(context).textTheme.labelLarge,
                  ),
                ],
              ),
              if (photo.notes case final notes? when notes.isNotEmpty) ...[
                const SizedBox(height: 14),
                Text(notes, style: Theme.of(context).textTheme.bodyLarge),
              ],
              const SizedBox(height: 22),
              if (controller.errorMessage case final message?) ...[
                AppErrorCard(message: message),
                const SizedBox(height: 14),
              ],
              FilledButton.icon(
                onPressed: controller.analyzingPhotoId == null
                    ? () async {
                        final result = await controller.analyze(photo);
                        if (result != null && context.mounted) {
                          await Navigator.of(context).push(
                            MaterialPageRoute<void>(
                              builder: (_) => _AssessmentPage(
                                title: 'AI 体态评估',
                                assessment: result,
                              ),
                            ),
                          );
                        }
                      }
                    : null,
                icon: controller.analyzingPhotoId == photo.id
                    ? const SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.auto_awesome_rounded),
                label: Text(
                  controller.analyzingPhotoId == photo.id
                      ? 'AI 正在分析，可能需要几十秒…'
                      : assessment == null
                      ? '进行 AI 评估'
                      : '重新评估',
                ),
              ),
              if (assessment != null) ...[
                const SizedBox(height: 18),
                AppSurface(
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => _AssessmentPage(
                        title: 'AI 体态评估',
                        assessment: assessment,
                      ),
                    ),
                  ),
                  child: Row(
                    children: [
                      const Icon(
                        Icons.auto_awesome_rounded,
                        color: AppColors.primary,
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '已完成 AI 评估',
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            const SizedBox(height: 3),
                            Text(
                              assessment.summary,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: Theme.of(context).textTheme.bodyMedium
                                  ?.copyWith(color: AppColors.muted),
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
              ],
            ],
          ),
        );
      },
    );
  }
}

class _AssessmentPage extends StatelessWidget {
  const _AssessmentPage({required this.title, required this.assessment});
  final String title;
  final BodyPhotoAssessment assessment;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 34),
        children: [
          AppSurface(
            color: AppColors.indigoSoft,
            borderColor: AppColors.indigoSoft,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const StatusPill(
                  label: 'AI 可观察结果',
                  color: AppColors.indigo,
                  icon: Icons.visibility_outlined,
                ),
                const SizedBox(height: 14),
                Text(
                  assessment.summary,
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
              ],
            ),
          ),
          if (assessment.observations.isNotEmpty) ...[
            const SizedBox(height: 24),
            const SectionTitle(title: '观察到的表现'),
            const SizedBox(height: 10),
            ...assessment.observations.map(
              (item) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: AppSurface(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item.observation,
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 7),
                      Text(
                        item.visualEvidence,
                        style: Theme.of(context).textTheme.bodyMedium
                            ?.copyWith(color: AppColors.muted),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
          if (assessment.trainingConsiderations.isNotEmpty)
            _BulletSection(
              title: '训练注意',
              items: assessment.trainingConsiderations,
            ),
          if (assessment.recommendedNextSteps.isNotEmpty)
            _BulletSection(
              title: '下一步建议',
              items: assessment.recommendedNextSteps,
            ),
          if (assessment.followUpQuestions.isNotEmpty)
            _BulletSection(title: '可继续补充', items: assessment.followUpQuestions),
          const SizedBox(height: 20),
          Text(
            assessment.disclaimer.isEmpty
                ? '仅基于照片中的可观察信息，不构成医学诊断或精确身体成分测量'
                : assessment.disclaimer,
            style: Theme.of(context).textTheme.labelMedium,
          ),
        ],
      ),
    );
  }
}

class _BulletSection extends StatelessWidget {
  const _BulletSection({required this.title, required this.items});
  final String title;
  final List<String> items;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 24),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionTitle(title: title),
        const SizedBox(height: 10),
        AppSurface(
          child: Column(
            children: [
              for (var index = 0; index < items.length; index++) ...[
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Padding(
                      padding: EdgeInsets.only(top: 7),
                      child: Icon(
                        Icons.circle,
                        size: 7,
                        color: AppColors.primary,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(child: Text(items[index])),
                  ],
                ),
                if (index < items.length - 1) const SizedBox(height: 12),
              ],
            ],
          ),
        ),
      ],
    ),
  );
}

class _ReportPreview extends StatelessWidget {
  const _ReportPreview({
    required this.report,
    required this.loading,
    required this.onTap,
  });
  final ProgressReport? report;
  final bool loading;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final value = report;
    if (value == null) {
      return AppSurface(
        onTap: loading ? null : onTap,
        child: Row(
          children: [
            Container(
              width: 52,
              height: 52,
              decoration: BoxDecoration(
                color: AppColors.mintSoft,
                borderRadius: BorderRadius.circular(17),
              ),
              child: loading
                  ? const Padding(
                      padding: EdgeInsets.all(15),
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.summarize_outlined, color: AppColors.mint),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '生成第一份阶段报告',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '汇总训练、饮食和身体数据',
                    style: Theme.of(context).textTheme.bodyMedium
                        ?.copyWith(color: AppColors.muted),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right_rounded, color: AppColors.muted),
          ],
        ),
      );
    }
    final count = value.training['workout_count'] ?? 0;
    return AppSurface(
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const StatusPill(
                label: '最近报告',
                color: AppColors.mint,
                icon: Icons.insights_rounded,
              ),
              const Spacer(),
              const Icon(Icons.chevron_right_rounded, color: AppColors.muted),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            '${_date(value.periodStart)} — ${_date(value.periodEnd)}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 5),
          Text(
            '$count 次训练 · ${value.recommendations.length} 条建议',
            style: Theme.of(context).textTheme.bodyMedium
                ?.copyWith(color: AppColors.muted),
          ),
        ],
      ),
    );
  }
}

class _ReportPage extends StatelessWidget {
  const _ReportPage({required this.report});
  final ProgressReport report;

  @override
  Widget build(BuildContext context) {
    final workoutCount = report.training['workout_count'] ?? 0;
    final duration = report.training['total_duration_minutes'] ?? 0;
    final completion = _percentage(report.training['completion_rate']);
    final weightChange = report.body['smoothed_change_kg'];
    return Scaffold(
      appBar: AppBar(title: const Text('阶段报告')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 34),
        children: [
          AppSurface(
            color: AppColors.darkCard,
            borderColor: AppColors.darkCard,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '阶段数据摘要',
                  style: Theme.of(context).textTheme.headlineSmall
                      ?.copyWith(color: Colors.white),
                ),
                const SizedBox(height: 5),
                Text(
                  '${_date(report.periodStart)} — ${_date(report.periodEnd)}',
                  style: Theme.of(context).textTheme.bodyMedium
                      ?.copyWith(color: Colors.white60),
                ),
                const SizedBox(height: 22),
                Row(
                  children: [
                    _ReportMetric(value: '$workoutCount', label: '训练次数'),
                    _ReportMetric(value: '$duration', label: '训练分钟'),
                    _ReportMetric(value: completion, label: '完成率'),
                  ],
                ),
              ],
            ),
          ),
          if (weightChange != null) ...[
            const SizedBox(height: 16),
            AppSurface(
              child: Row(
                children: [
                  const Icon(
                    Icons.monitor_weight_outlined,
                    color: AppColors.indigo,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      '平滑体重变化',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                  Text(
                    '$weightChange kg',
                    style: Theme.of(context).textTheme.titleMedium
                        ?.copyWith(color: AppColors.indigo),
                  ),
                ],
              ),
            ),
          ],
          if (report.recommendations.isNotEmpty)
            _BulletSection(title: '下一阶段建议', items: report.recommendations),
          if (report.missingData.isNotEmpty) ...[
            const SizedBox(height: 24),
            const SectionTitle(title: '数据完整度'),
            const SizedBox(height: 10),
            AppSurface(
              color: AppColors.amberSoft,
              borderColor: AppColors.amberSoft,
              child: Text(
                '还缺少：${report.missingData.map(_missingLabel).join('、')}。持续记录后报告会更准确。',
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _ReportMetric extends StatelessWidget {
  const _ReportMetric({required this.value, required this.label});
  final String value;
  final String label;

  @override
  Widget build(BuildContext context) => Expanded(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          value,
          style: Theme.of(context).textTheme.headlineMedium
              ?.copyWith(color: Colors.white),
        ),
        const SizedBox(height: 3),
        Text(
          label,
          style: Theme.of(context).textTheme.labelMedium
              ?.copyWith(color: Colors.white54),
        ),
      ],
    ),
  );
}

class _PhotoDraft {
  const _PhotoDraft({
    required this.bytes,
    required this.view,
    required this.capturedAt,
    this.notes,
  });
  final Uint8List bytes;
  final BodyPhotoView view;
  final DateTime capturedAt;
  final String? notes;
}

class _PhotoDetailsSheet extends StatefulWidget {
  const _PhotoDetailsSheet({required this.bytes});
  final Uint8List bytes;

  @override
  State<_PhotoDetailsSheet> createState() => _PhotoDetailsSheetState();
}

class _PhotoDetailsSheetState extends State<_PhotoDetailsSheet> {
  final _notes = TextEditingController();
  BodyPhotoView _view = BodyPhotoView.front;
  DateTime _capturedAt = DateTime.now();

  @override
  void dispose() {
    _notes.dispose();
    super.dispose();
  }

  Future<void> _pickDate() async {
    final date = await showDatePicker(
      context: context,
      initialDate: _capturedAt,
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
    );
    if (date != null) {
      setState(
        () => _capturedAt = DateTime(date.year, date.month, date.day, 12),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('确认照片信息', style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 14),
            ClipRRect(
              borderRadius: BorderRadius.circular(20),
              child: SizedBox(
                height: 210,
                child: Image.memory(widget.bytes, fit: BoxFit.cover),
              ),
            ),
            const SizedBox(height: 17),
            Text('拍摄角度', style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 9),
            SegmentedButton<BodyPhotoView>(
              segments: BodyPhotoView.values
                  .map(
                    (view) =>
                        ButtonSegment(value: view, label: Text(view.label)),
                  )
                  .toList(growable: false),
              selected: {_view},
              onSelectionChanged: (value) =>
                  setState(() => _view = value.single),
            ),
            const SizedBox(height: 13),
            OutlinedButton.icon(
              onPressed: _pickDate,
              icon: const Icon(Icons.calendar_today_rounded, size: 18),
              label: Text('拍摄日期：${_date(_capturedAt)}'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _notes,
              maxLength: 2000,
              minLines: 2,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: '备注（可选）',
                hintText: '例如：晨起、训练前、自然站立',
                counterText: '',
              ),
            ),
            const SizedBox(height: 18),
            FilledButton(
              onPressed: () {
                final notes = _notes.text.trim();
                Navigator.pop(
                  context,
                  _PhotoDraft(
                    bytes: widget.bytes,
                    view: _view,
                    capturedAt: _capturedAt,
                    notes: notes.isEmpty ? null : notes,
                  ),
                );
              },
              child: const Text('上传并保存'),
            ),
          ],
        ),
      ),
    );
  }
}

class _CompareSheet extends StatefulWidget {
  const _CompareSheet({required this.photos});
  final List<BodyProgressPhoto> photos;

  @override
  State<_CompareSheet> createState() => _CompareSheetState();
}

class _CompareSheetState extends State<_CompareSheet> {
  late BodyProgressPhoto before = widget.photos.last;
  late BodyProgressPhoto after = widget.photos.first;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('选择对比照片', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 7),
          Text(
            '请选择较早和较新的两张照片，尽量保持角度一致。',
            style: Theme.of(context).textTheme.bodyMedium
                ?.copyWith(color: AppColors.muted),
          ),
          const SizedBox(height: 18),
          _photoDropdown(
            label: '较早照片',
            value: before,
            onChanged: (value) => setState(() => before = value!),
          ),
          const SizedBox(height: 12),
          _photoDropdown(
            label: '较新照片',
            value: after,
            onChanged: (value) => setState(() => after = value!),
          ),
          const SizedBox(height: 18),
          FilledButton.icon(
            onPressed: before.id == after.id
                ? null
                : () => Navigator.pop(context, (before, after)),
            icon: const Icon(Icons.auto_awesome_rounded),
            label: const Text('开始 AI 对比'),
          ),
        ],
      ),
    );
  }

  Widget _photoDropdown({
    required String label,
    required BodyProgressPhoto value,
    required ValueChanged<BodyProgressPhoto?> onChanged,
  }) => DropdownButtonFormField<BodyProgressPhoto>(
    initialValue: value,
    decoration: InputDecoration(labelText: label),
    items: widget.photos
        .map(
          (photo) => DropdownMenuItem(
            value: photo,
            child: Text('${_date(photo.capturedAt)} · ${photo.view.label}'),
          ),
        )
        .toList(growable: false),
    onChanged: onChanged,
  );
}

String _date(DateTime raw) {
  final value = raw.toLocal();
  return '${value.year}.${value.month.toString().padLeft(2, '0')}.${value.day.toString().padLeft(2, '0')}';
}

String _percentage(Object? value) {
  final number = switch (value) {
    num current => current.toDouble(),
    String current => double.tryParse(current) ?? 0,
    _ => 0.0,
  };
  return '${(number * 100).round()}%';
}

String _missingLabel(String value) => switch (value) {
  'training' => '训练记录',
  'nutrition' => '饮食记录',
  'body' => '身体数据',
  _ => value,
};

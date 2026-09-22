import 'dart:ui' show lerpDouble;

import 'package:flutter/material.dart';

import '../../../../core/theme/app_theme.dart';
import '../../../../core/widgets/app_widgets.dart';

enum ExerciseMotionKind {
  squat,
  hinge,
  lunge,
  horizontalPush,
  horizontalPull,
  verticalPush,
  verticalPull,
  curl,
  core,
  generic,
}

ExerciseMotionKind exerciseMotionKind(String name, String? movementPattern) {
  final value = '${name.toLowerCase()} ${movementPattern?.toLowerCase() ?? ''}';
  bool has(Iterable<String> words) => words.any(value.contains);

  if (has(const ['深蹲', 'squat'])) return ExerciseMotionKind.squat;
  if (has(const ['硬拉', '髋铰链', '俯身', 'deadlift', 'hinge'])) {
    return ExerciseMotionKind.hinge;
  }
  if (has(const ['弓步', '箭步', 'lunge', 'split_squat'])) {
    return ExerciseMotionKind.lunge;
  }
  if (has(const ['推举', '肩推', 'overhead_press', 'vertical_push'])) {
    return ExerciseMotionKind.verticalPush;
  }
  if (has(const [
    '引体',
    '下拉',
    'pullup',
    'pull_up',
    'pulldown',
    'vertical_pull',
  ])) {
    return ExerciseMotionKind.verticalPull;
  }
  if (has(const ['划船', 'row', 'horizontal_pull'])) {
    return ExerciseMotionKind.horizontalPull;
  }
  if (has(const [
    '卧推',
    '俯卧撑',
    '胸推',
    'bench',
    'pushup',
    'push_up',
    'horizontal_push',
  ])) {
    return ExerciseMotionKind.horizontalPush;
  }
  if (has(const ['弯举', '臂屈伸', 'curl', 'extension'])) {
    return ExerciseMotionKind.curl;
  }
  if (has(const ['平板', '卷腹', '核心', 'plank', 'crunch', 'core'])) {
    return ExerciseMotionKind.core;
  }
  return ExerciseMotionKind.generic;
}

class AnatomyMotionIllustration extends StatefulWidget {
  const AnatomyMotionIllustration({
    super.key,
    required this.name,
    required this.equipment,
    required this.primaryMuscles,
    required this.secondaryMuscles,
    this.movementPattern,
  });

  final String name;
  final String? movementPattern;
  final String equipment;
  final List<String> primaryMuscles;
  final List<String> secondaryMuscles;

  @override
  State<AnatomyMotionIllustration> createState() =>
      _AnatomyMotionIllustrationState();
}

class _AnatomyMotionIllustrationState extends State<AnatomyMotionIllustration>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  bool _paused = false;
  bool _reduceMotion = false;

  ExerciseMotionKind get _kind =>
      exerciseMotionKind(widget.name, widget.movementPattern);

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat(reverse: true);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final reduceMotion = MediaQuery.disableAnimationsOf(context);
    if (reduceMotion == _reduceMotion) return;
    _reduceMotion = reduceMotion;
    if (reduceMotion) {
      _controller
        ..stop()
        ..value = 0.58;
    } else if (!_paused) {
      _controller.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _togglePlayback() {
    if (_reduceMotion) return;
    setState(() => _paused = !_paused);
    if (_paused) {
      _controller.stop();
    } else {
      _controller.repeat(reverse: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 16, 10, 8),
            child: Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: AppColors.primarySoft,
                    borderRadius: BorderRadius.circular(11),
                  ),
                  child: const Icon(
                    Icons.motion_photos_auto_rounded,
                    color: AppColors.primary,
                    size: 20,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '动态解剖示意',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      Text(
                        _motionCaption(_kind),
                        style: Theme.of(context).textTheme.labelMedium,
                      ),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: _reduceMotion
                      ? '系统已开启减少动态效果'
                      : (_paused ? '播放' : '暂停'),
                  onPressed: _reduceMotion ? null : _togglePlayback,
                  icon: Icon(
                    _paused || _reduceMotion
                        ? Icons.play_arrow_rounded
                        : Icons.pause_rounded,
                  ),
                ),
              ],
            ),
          ),
          Semantics(
            image: true,
            label: '${widget.name}动态解剖示意，红色显示主练肌群，黄色显示辅助肌群',
            child: SizedBox(
              height: 250,
              child: AnimatedBuilder(
                animation: _controller,
                builder: (context, _) => CustomPaint(
                  painter: _AnatomyMotionPainter(
                    progress: Curves.easeInOut.transform(_controller.value),
                    kind: _kind,
                    equipment: widget.equipment,
                    primaryMuscles: widget.primaryMuscles,
                    secondaryMuscles: widget.secondaryMuscles,
                  ),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 5, 18, 17),
            child: Row(
              children: [
                const _LegendDot(color: AppColors.primary, label: '主要发力'),
                const SizedBox(width: 16),
                const _LegendDot(color: AppColors.amber, label: '辅助发力'),
                const Spacer(),
                Text('动作轨迹示意', style: Theme.of(context).textTheme.labelMedium),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _LegendDot extends StatelessWidget {
  const _LegendDot({required this.color, required this.label});

  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 9,
          height: 9,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 5),
        Text(label, style: Theme.of(context).textTheme.labelMedium),
      ],
    );
  }
}

class _AnatomyMotionPainter extends CustomPainter {
  const _AnatomyMotionPainter({
    required this.progress,
    required this.kind,
    required this.equipment,
    required this.primaryMuscles,
    required this.secondaryMuscles,
  });

  final double progress;
  final ExerciseMotionKind kind;
  final String equipment;
  final List<String> primaryMuscles;
  final List<String> secondaryMuscles;

  @override
  void paint(Canvas canvas, Size size) {
    final scale = (size.height - 18) / 150;
    final horizontalScale = size.width / 150;
    final actualScale = scale < horizontalScale ? scale : horizontalScale;
    final origin = Offset(
      (size.width - 150 * actualScale) / 2,
      (size.height - 150 * actualScale) / 2,
    );
    canvas
      ..save()
      ..translate(origin.dx, origin.dy)
      ..scale(actualScale);

    final guide = Paint()
      ..color = AppColors.line.withValues(alpha: 0.75)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    canvas.drawOval(const Rect.fromLTWH(18, 136, 114, 8), guide);
    canvas.drawLine(const Offset(75, 10), const Offset(75, 140), guide);

    final pose = _poseAt(kind, progress);
    _drawMuscles(canvas, pose, secondaryMuscles, AppColors.amber, 7);
    _drawMuscles(canvas, pose, primaryMuscles, AppColors.primary, 9);
    _drawBody(canvas, pose);
    _drawEquipment(canvas, pose, equipment, kind);
    _drawMotionGuide(canvas, pose, kind, progress);
    canvas.restore();
  }

  void _drawBody(Canvas canvas, _Pose pose) {
    final bone = Paint()
      ..color = AppColors.ink.withValues(alpha: 0.78)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3.4
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final joint = Paint()
      ..color = AppColors.surface
      ..style = PaintingStyle.fill;
    final jointLine = Paint()
      ..color = AppColors.ink.withValues(alpha: 0.72)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.7;

    canvas.drawCircle(pose.head, 9, bone);
    canvas.drawLine(pose.neck, pose.hipCenter, bone);
    canvas.drawLine(pose.leftShoulder, pose.rightShoulder, bone);
    canvas.drawLine(pose.leftHip, pose.rightHip, bone);
    for (final segment in [
      (pose.leftShoulder, pose.leftElbow),
      (pose.leftElbow, pose.leftHand),
      (pose.rightShoulder, pose.rightElbow),
      (pose.rightElbow, pose.rightHand),
      (pose.leftHip, pose.leftKnee),
      (pose.leftKnee, pose.leftAnkle),
      (pose.rightHip, pose.rightKnee),
      (pose.rightKnee, pose.rightAnkle),
    ]) {
      canvas.drawLine(segment.$1, segment.$2, bone);
    }
    for (final point in [
      pose.leftShoulder,
      pose.rightShoulder,
      pose.leftElbow,
      pose.rightElbow,
      pose.leftHip,
      pose.rightHip,
      pose.leftKnee,
      pose.rightKnee,
    ]) {
      canvas
        ..drawCircle(point, 3.2, joint)
        ..drawCircle(point, 3.2, jointLine);
    }
  }

  void _drawMuscles(
    Canvas canvas,
    _Pose pose,
    List<String> muscles,
    Color color,
    double width,
  ) {
    if (muscles.isEmpty) return;
    final paint = Paint()
      ..color = color.withValues(alpha: 0.8)
      ..style = PaintingStyle.stroke
      ..strokeWidth = width
      ..strokeCap = StrokeCap.round;
    final fill = Paint()
      ..color = color.withValues(alpha: 0.38)
      ..style = PaintingStyle.fill;
    bool has(Iterable<String> names) => muscles.any(names.contains);

    if (has(const ['chest', 'pectorals'])) {
      canvas.drawOval(
        Rect.fromCenter(center: pose.chest, width: 24, height: 13),
        fill,
      );
    }
    if (has(const ['back', 'lats', 'latissimus'])) {
      canvas.drawLine(pose.neck, pose.hipCenter, paint);
    }
    if (has(const ['shoulders', 'deltoids'])) {
      canvas
        ..drawCircle(pose.leftShoulder, width * 0.65, fill)
        ..drawCircle(pose.rightShoulder, width * 0.65, fill);
    }
    if (has(const ['biceps', 'triceps', 'arms'])) {
      canvas
        ..drawLine(pose.leftShoulder, pose.leftElbow, paint)
        ..drawLine(pose.rightShoulder, pose.rightElbow, paint);
    }
    if (has(const ['forearms'])) {
      canvas
        ..drawLine(pose.leftElbow, pose.leftHand, paint)
        ..drawLine(pose.rightElbow, pose.rightHand, paint);
    }
    if (has(const ['core', 'abs', 'abdominals'])) {
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromCenter(center: pose.core, width: 14, height: 24),
          const Radius.circular(6),
        ),
        fill,
      );
    }
    if (has(const ['gluteus', 'glutes'])) {
      canvas.drawOval(
        Rect.fromCenter(center: pose.hipCenter, width: 22, height: 14),
        fill,
      );
    }
    if (has(const ['quadriceps', 'hamstrings', 'adductors'])) {
      canvas
        ..drawLine(pose.leftHip, pose.leftKnee, paint)
        ..drawLine(pose.rightHip, pose.rightKnee, paint);
    }
    if (has(const ['calves'])) {
      canvas
        ..drawLine(pose.leftKnee, pose.leftAnkle, paint)
        ..drawLine(pose.rightKnee, pose.rightAnkle, paint);
    }
  }

  void _drawEquipment(
    Canvas canvas,
    _Pose pose,
    String equipment,
    ExerciseMotionKind kind,
  ) {
    final line = Paint()
      ..color = AppColors.indigo
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.5
      ..strokeCap = StrokeCap.round;
    if (equipment == 'barbell') {
      final y = kind == ExerciseMotionKind.squat
          ? (pose.leftShoulder.dy + pose.rightShoulder.dy) / 2 - 2
          : (pose.leftHand.dy + pose.rightHand.dy) / 2;
      canvas.drawLine(Offset(38, y), Offset(112, y), line);
      for (final x in const [35.0, 39.0, 111.0, 115.0]) {
        canvas.drawLine(Offset(x, y - 6), Offset(x, y + 6), line);
      }
    } else if (equipment == 'dumbbell') {
      for (final hand in [pose.leftHand, pose.rightHand]) {
        canvas.drawLine(
          Offset(hand.dx - 5, hand.dy),
          Offset(hand.dx + 5, hand.dy),
          line,
        );
        canvas.drawLine(
          Offset(hand.dx - 5, hand.dy - 3),
          Offset(hand.dx - 5, hand.dy + 3),
          line,
        );
        canvas.drawLine(
          Offset(hand.dx + 5, hand.dy - 3),
          Offset(hand.dx + 5, hand.dy + 3),
          line,
        );
      }
    } else if (equipment == 'cable' || equipment == 'machine') {
      canvas.drawLine(const Offset(127, 18), const Offset(127, 132), line);
      canvas.drawCircle(const Offset(127, 22), 4, line);
      canvas.drawLine(const Offset(127, 22), pose.rightHand, line);
    }
  }

  void _drawMotionGuide(
    Canvas canvas,
    _Pose pose,
    ExerciseMotionKind kind,
    double progress,
  ) {
    final guide = Paint()
      ..color = AppColors.mint.withValues(alpha: 0.75)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round;
    final marker = Paint()
      ..color = AppColors.mint
      ..style = PaintingStyle.fill;
    final target = switch (kind) {
      ExerciseMotionKind.squat || ExerciseMotionKind.lunge => pose.hipCenter,
      ExerciseMotionKind.hinge || ExerciseMotionKind.core => pose.chest,
      _ => Offset(
        (pose.leftHand.dx + pose.rightHand.dx) / 2,
        (pose.leftHand.dy + pose.rightHand.dy) / 2,
      ),
    };
    canvas.drawCircle(target, 2.2 + progress * 1.6, marker);
    canvas.drawArc(
      Rect.fromCircle(center: target, radius: 8 + progress * 3),
      -1.2,
      1.8,
      false,
      guide,
    );
  }

  @override
  bool shouldRepaint(covariant _AnatomyMotionPainter oldDelegate) =>
      oldDelegate.progress != progress ||
      oldDelegate.kind != kind ||
      oldDelegate.equipment != equipment ||
      oldDelegate.primaryMuscles != primaryMuscles ||
      oldDelegate.secondaryMuscles != secondaryMuscles;
}

class _Pose {
  const _Pose({
    required this.head,
    required this.neck,
    required this.leftShoulder,
    required this.rightShoulder,
    required this.leftElbow,
    required this.rightElbow,
    required this.leftHand,
    required this.rightHand,
    required this.leftHip,
    required this.rightHip,
    required this.leftKnee,
    required this.rightKnee,
    required this.leftAnkle,
    required this.rightAnkle,
  });

  final Offset head;
  final Offset neck;
  final Offset leftShoulder;
  final Offset rightShoulder;
  final Offset leftElbow;
  final Offset rightElbow;
  final Offset leftHand;
  final Offset rightHand;
  final Offset leftHip;
  final Offset rightHip;
  final Offset leftKnee;
  final Offset rightKnee;
  final Offset leftAnkle;
  final Offset rightAnkle;

  Offset get hipCenter =>
      Offset((leftHip.dx + rightHip.dx) / 2, (leftHip.dy + rightHip.dy) / 2);

  Offset get chest => Offset(
    (leftShoulder.dx + rightShoulder.dx) / 2,
    (leftShoulder.dy + hipCenter.dy) / 2,
  );

  Offset get core =>
      Offset((chest.dx + hipCenter.dx) / 2, (chest.dy + hipCenter.dy) / 2);

  static _Pose lerp(_Pose a, _Pose b, double t) => _Pose(
    head: Offset.lerp(a.head, b.head, t)!,
    neck: Offset.lerp(a.neck, b.neck, t)!,
    leftShoulder: Offset.lerp(a.leftShoulder, b.leftShoulder, t)!,
    rightShoulder: Offset.lerp(a.rightShoulder, b.rightShoulder, t)!,
    leftElbow: Offset.lerp(a.leftElbow, b.leftElbow, t)!,
    rightElbow: Offset.lerp(a.rightElbow, b.rightElbow, t)!,
    leftHand: Offset.lerp(a.leftHand, b.leftHand, t)!,
    rightHand: Offset.lerp(a.rightHand, b.rightHand, t)!,
    leftHip: Offset.lerp(a.leftHip, b.leftHip, t)!,
    rightHip: Offset.lerp(a.rightHip, b.rightHip, t)!,
    leftKnee: Offset.lerp(a.leftKnee, b.leftKnee, t)!,
    rightKnee: Offset.lerp(a.rightKnee, b.rightKnee, t)!,
    leftAnkle: Offset.lerp(a.leftAnkle, b.leftAnkle, t)!,
    rightAnkle: Offset.lerp(a.rightAnkle, b.rightAnkle, t)!,
  );
}

const _neutralPose = _Pose(
  head: Offset(75, 15),
  neck: Offset(75, 29),
  leftShoulder: Offset(60, 39),
  rightShoulder: Offset(90, 39),
  leftElbow: Offset(55, 64),
  rightElbow: Offset(95, 64),
  leftHand: Offset(53, 86),
  rightHand: Offset(97, 86),
  leftHip: Offset(67, 78),
  rightHip: Offset(83, 78),
  leftKnee: Offset(66, 108),
  rightKnee: Offset(84, 108),
  leftAnkle: Offset(64, 138),
  rightAnkle: Offset(86, 138),
);

_Pose _poseAt(ExerciseMotionKind kind, double progress) {
  final target = switch (kind) {
    ExerciseMotionKind.squat => const _Pose(
      head: Offset(75, 31),
      neck: Offset(75, 45),
      leftShoulder: Offset(60, 54),
      rightShoulder: Offset(90, 54),
      leftElbow: Offset(57, 63),
      rightElbow: Offset(93, 63),
      leftHand: Offset(67, 57),
      rightHand: Offset(83, 57),
      leftHip: Offset(64, 96),
      rightHip: Offset(86, 96),
      leftKnee: Offset(52, 114),
      rightKnee: Offset(98, 114),
      leftAnkle: Offset(61, 138),
      rightAnkle: Offset(89, 138),
    ),
    ExerciseMotionKind.hinge => const _Pose(
      head: Offset(104, 45),
      neck: Offset(94, 52),
      leftShoulder: Offset(81, 51),
      rightShoulder: Offset(103, 60),
      leftElbow: Offset(84, 78),
      rightElbow: Offset(104, 84),
      leftHand: Offset(83, 103),
      rightHand: Offset(102, 105),
      leftHip: Offset(67, 79),
      rightHip: Offset(84, 80),
      leftKnee: Offset(64, 107),
      rightKnee: Offset(85, 108),
      leftAnkle: Offset(62, 138),
      rightAnkle: Offset(87, 138),
    ),
    ExerciseMotionKind.lunge => const _Pose(
      head: Offset(75, 26),
      neck: Offset(75, 40),
      leftShoulder: Offset(60, 50),
      rightShoulder: Offset(90, 50),
      leftElbow: Offset(55, 71),
      rightElbow: Offset(95, 71),
      leftHand: Offset(53, 91),
      rightHand: Offset(97, 91),
      leftHip: Offset(66, 88),
      rightHip: Offset(84, 88),
      leftKnee: Offset(48, 110),
      rightKnee: Offset(96, 119),
      leftAnkle: Offset(34, 138),
      rightAnkle: Offset(103, 138),
    ),
    ExerciseMotionKind.horizontalPush => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(42, 47),
      rightElbow: Offset(108, 47),
      leftHand: Offset(22, 47),
      rightHand: Offset(128, 47),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.horizontalPull => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(47, 49),
      rightElbow: Offset(103, 49),
      leftHand: Offset(65, 49),
      rightHand: Offset(85, 49),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.verticalPush => const _Pose(
      head: Offset(75, 18),
      neck: Offset(75, 31),
      leftShoulder: Offset(60, 41),
      rightShoulder: Offset(90, 41),
      leftElbow: Offset(57, 23),
      rightElbow: Offset(93, 23),
      leftHand: Offset(62, 5),
      rightHand: Offset(88, 5),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.verticalPull => const _Pose(
      head: Offset(75, 18),
      neck: Offset(75, 31),
      leftShoulder: Offset(60, 41),
      rightShoulder: Offset(90, 41),
      leftElbow: Offset(43, 38),
      rightElbow: Offset(107, 38),
      leftHand: Offset(59, 22),
      rightHand: Offset(91, 22),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.curl => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(56, 65),
      rightElbow: Offset(94, 65),
      leftHand: Offset(63, 45),
      rightHand: Offset(87, 45),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.core => const _Pose(
      head: Offset(91, 29),
      neck: Offset(84, 39),
      leftShoulder: Offset(69, 45),
      rightShoulder: Offset(94, 51),
      leftElbow: Offset(58, 65),
      rightElbow: Offset(104, 68),
      leftHand: Offset(63, 83),
      rightHand: Offset(95, 84),
      leftHip: Offset(67, 79),
      rightHip: Offset(83, 79),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.generic => _neutralPose,
  };
  final breathing = kind == ExerciseMotionKind.generic
      ? (0.03 * progress)
      : 0.0;
  final pose = _Pose.lerp(_neutralPose, target, progress);
  if (breathing == 0) return pose;
  return _Pose(
    head: pose.head,
    neck: pose.neck,
    leftShoulder: Offset(
      lerpDouble(pose.leftShoulder.dx, pose.leftShoulder.dx - 2, progress)!,
      pose.leftShoulder.dy,
    ),
    rightShoulder: Offset(
      lerpDouble(pose.rightShoulder.dx, pose.rightShoulder.dx + 2, progress)!,
      pose.rightShoulder.dy,
    ),
    leftElbow: pose.leftElbow,
    rightElbow: pose.rightElbow,
    leftHand: pose.leftHand,
    rightHand: pose.rightHand,
    leftHip: pose.leftHip,
    rightHip: pose.rightHip,
    leftKnee: pose.leftKnee,
    rightKnee: pose.rightKnee,
    leftAnkle: pose.leftAnkle,
    rightAnkle: pose.rightAnkle,
  );
}

String _motionCaption(ExerciseMotionKind kind) => switch (kind) {
  ExerciseMotionKind.squat => '观察髋、膝同步屈伸',
  ExerciseMotionKind.hinge => '观察髋部后移与躯干前倾',
  ExerciseMotionKind.lunge => '观察前后腿协同和重心下降',
  ExerciseMotionKind.horizontalPush => '观察手臂水平推出轨迹',
  ExerciseMotionKind.horizontalPull => '观察肘部向后收紧轨迹',
  ExerciseMotionKind.verticalPush => '观察手臂垂直推举轨迹',
  ExerciseMotionKind.verticalPull => '观察肩胛下沉与肘部下拉',
  ExerciseMotionKind.curl => '观察肘关节屈伸轨迹',
  ExerciseMotionKind.core => '观察躯干稳定与屈曲轨迹',
  ExerciseMotionKind.generic => '观察关节轨迹与主要发力区域',
};

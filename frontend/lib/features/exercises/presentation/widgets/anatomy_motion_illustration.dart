import 'dart:ui' show lerpDouble;

import 'package:flutter/material.dart';

import '../../../../core/theme/app_theme.dart';
import '../../../../core/widgets/app_widgets.dart';
import '../../domain/exercise_models.dart' show muscleLabel;

enum ExerciseMotionKind {
  squat,
  hinge,
  lunge,
  benchPress,
  horizontalPush,
  singleArmRow,
  bentOverRow,
  seatedRow,
  facePull,
  horizontalPull,
  verticalPush,
  straightArmPulldown,
  pullUp,
  verticalPull,
  curl,
  overheadExtension,
  elbowExtension,
  lateralRaise,
  singleArmLateralRaise,
  chestFly,
  lowToHighFly,
  reverseFly,
  hipExtension,
  hipAbduction,
  rotation,
  pushUp,
  plank,
  gluteBridge,
  kneelingCrunch,
  core,
  generic,
}

ExerciseMotionKind exerciseMotionKind(String name, String? movementPattern) {
  final value = '${name.toLowerCase()} ${movementPattern?.toLowerCase() ?? ''}';
  bool has(Iterable<String> words) => words.any(value.contains);

  // Reverse fly must be resolved before generic "fly" and "hinge" matches.
  // Its working direction is opening the arms, opposite to a chest fly.
  if (has(const [
    '反向飞鸟',
    '后束飞鸟',
    'reverse_fly',
    'reverse fly',
    'rear_delt_fly',
  ])) {
    return ExerciseMotionKind.reverseFly;
  }
  if (has(const ['俯卧撑', '伏地挺身', 'pushup', 'push_up'])) {
    return ExerciseMotionKind.pushUp;
  }
  if (has(const ['平板支撑', 'plank'])) return ExerciseMotionKind.plank;
  if (has(const ['臀桥', 'glute_bridge'])) {
    return ExerciseMotionKind.gluteBridge;
  }
  if (has(const ['跪姿绳索卷腹', '绳索卷腹', 'kneeling_crunch'])) {
    return ExerciseMotionKind.kneelingCrunch;
  }
  if (has(const ['卧推', 'bench_press', 'bench press'])) {
    return ExerciseMotionKind.benchPress;
  }
  if (has(const ['面拉', 'face_pull', 'face pull'])) {
    return ExerciseMotionKind.facePull;
  }
  if (has(const ['直臂下压', '直臂下拉', 'straight_arm_pulldown'])) {
    return ExerciseMotionKind.straightArmPulldown;
  }
  if (has(const ['引体向上', '辅助引体', 'pullup', 'pull_up'])) {
    return ExerciseMotionKind.pullUp;
  }
  if (has(const ['坐姿划船', 'seated_row'])) {
    return ExerciseMotionKind.seatedRow;
  }
  if (has(const ['单臂哑铃划船', '单手哑铃划船', 'one_arm_row'])) {
    return ExerciseMotionKind.singleArmRow;
  }
  if (has(const ['杠铃划船', '哑铃划船', '胸托哑铃划船', 'bent_over_row'])) {
    return ExerciseMotionKind.bentOverRow;
  }
  if (has(const ['过顶臂屈伸', '颈后臂屈伸', 'overhead_extension'])) {
    return ExerciseMotionKind.overheadExtension;
  }
  if (has(const ['绳索上斜夹胸', '低位绳索夹胸', 'low_to_high_fly'])) {
    return ExerciseMotionKind.lowToHighFly;
  }
  if (has(const ['绳索侧平举', '单臂绳索侧平举'])) {
    return ExerciseMotionKind.singleArmLateralRaise;
  }
  if (has(const ['深蹲', 'squat'])) return ExerciseMotionKind.squat;
  if (has(const ['硬拉', '髋铰链', '俯身', 'deadlift', 'hinge'])) {
    return ExerciseMotionKind.hinge;
  }
  if (has(const ['弓步', '箭步', 'lunge', 'split_squat'])) {
    return ExerciseMotionKind.lunge;
  }
  if (has(const [
    '侧平举',
    '肩部飞鸟',
    '站姿飞鸟',
    '站姿哑铃飞鸟',
    'shoulder_abduction',
    'lateral_raise',
  ])) {
    return ExerciseMotionKind.lateralRaise;
  }
  if (has(const ['飞鸟', '夹胸', 'chest_fly', 'horizontal_adduction'])) {
    return ExerciseMotionKind.chestFly;
  }
  if (has(const ['臂屈伸', '三头下压', 'elbow_extension', 'pushdown'])) {
    return ExerciseMotionKind.elbowExtension;
  }
  if (has(const ['后踢', 'hip_extension', 'kickback'])) {
    return ExerciseMotionKind.hipExtension;
  }
  if (has(const ['髋外展', '侧抬腿', 'hip_abduction'])) {
    return ExerciseMotionKind.hipAbduction;
  }
  if (has(const ['伐木', '转体', 'rotation', 'wood_chop'])) {
    return ExerciseMotionKind.rotation;
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
  if (has(const ['弯举', 'curl'])) {
    return ExerciseMotionKind.curl;
  }
  if (has(const ['平板', '卷腹', '核心', 'plank', 'crunch', 'core'])) {
    return ExerciseMotionKind.core;
  }
  return ExerciseMotionKind.generic;
}

double anatomyMotionProgress(double cycleValue) {
  final value = cycleValue.clamp(0.0, 1.0);
  if (value <= 0.12) return 0;
  if (value >= 0.78) return 1;
  return Curves.easeInOut.transform((value - 0.12) / 0.66);
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
      duration: const Duration(milliseconds: 2100),
    )..repeat();
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
      _controller.repeat();
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
      _controller.repeat();
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
                        _motionCaption(_kind, widget.equipment),
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
            label: '${widget.name}动态解剖示意，红色显示主练肌群，黄色显示辅助肌群，绿色箭头显示动作方向',
            child: SizedBox(
              height: 300,
              child: AnimatedBuilder(
                animation: _controller,
                builder: (context, _) {
                  final progress = anatomyMotionProgress(_controller.value);
                  return Stack(
                    fit: StackFit.expand,
                    children: [
                      DecoratedBox(
                        decoration: BoxDecoration(
                          gradient: LinearGradient(
                            begin: Alignment.topCenter,
                            end: Alignment.bottomCenter,
                            colors: [
                              AppColors.indigoSoft.withValues(alpha: 0.55),
                              AppColors.surface,
                            ],
                          ),
                        ),
                      ),
                      CustomPaint(
                        painter: _AnatomyMotionPainter(
                          progress: progress,
                          kind: _kind,
                          equipment: widget.equipment,
                          primaryMuscles: widget.primaryMuscles,
                          secondaryMuscles: widget.secondaryMuscles,
                        ),
                      ),
                      Positioned(
                        left: 14,
                        top: 12,
                        child: _StagePill(
                          icon: progress < 0.48
                              ? Icons.accessibility_new_rounded
                              : Icons.local_fire_department_rounded,
                          label: _stageLabel(_kind, progress),
                        ),
                      ),
                      Positioned(
                        right: 14,
                        top: 12,
                        child: _StagePill(
                          icon: Icons.arrow_forward_rounded,
                          label: _directionLabel(_kind),
                        ),
                      ),
                    ],
                  );
                },
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 5, 18, 17),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Row(
                  children: [
                    _LegendDot(color: AppColors.primary, label: '主要发力'),
                    SizedBox(width: 16),
                    _LegendDot(color: AppColors.amber, label: '辅助稳定'),
                    SizedBox(width: 16),
                    _LegendDot(color: AppColors.mint, label: '动作方向'),
                  ],
                ),
                const SizedBox(height: 9),
                Text(
                  '主练：${widget.primaryMuscles.map(muscleLabel).join('、')}',
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                if (widget.secondaryMuscles.isNotEmpty) ...[
                  const SizedBox(height: 3),
                  Text(
                    '辅助：${widget.secondaryMuscles.map(muscleLabel).join('、')}',
                    style: Theme.of(context).textTheme.labelMedium,
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

class _StagePill extends StatelessWidget {
  const _StagePill({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: AppColors.surface.withValues(alpha: 0.9),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppColors.line),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 15, color: AppColors.mint),
            const SizedBox(width: 5),
            Text(label, style: Theme.of(context).textTheme.labelSmall),
          ],
        ),
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
      ..color = AppColors.line.withValues(alpha: 0.55)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.8;
    final usesBench =
        kind == ExerciseMotionKind.benchPress ||
        (kind == ExerciseMotionKind.chestFly && equipment == 'dumbbell');
    final usesFloor =
        kind == ExerciseMotionKind.pushUp ||
        kind == ExerciseMotionKind.plank ||
        kind == ExerciseMotionKind.gluteBridge;
    if (usesBench) {
      _drawBench(canvas);
    } else if (usesFloor) {
      canvas.drawLine(const Offset(10, 126), const Offset(140, 126), guide);
    } else {
      for (final y in const [35.0, 70.0, 105.0]) {
        canvas.drawLine(Offset(16, y), Offset(134, y), guide);
      }
      canvas.drawOval(const Rect.fromLTWH(15, 136, 120, 8), guide);
    }
    if (kind == ExerciseMotionKind.singleArmRow) {
      _drawRowSupport(canvas);
    }

    final pose = _poseAt(kind, progress);
    _drawBody(canvas, _poseAt(kind, 0), ghost: true);
    _drawBody(canvas, pose);
    _drawMuscles(canvas, pose, secondaryMuscles, AppColors.amber, 6.5);
    _drawMuscles(canvas, pose, primaryMuscles, AppColors.primary, 8.5);
    _drawEquipment(canvas, pose, equipment, kind);
    _drawMotionGuide(canvas, pose, kind, progress);
    canvas.restore();
  }

  void _drawBench(Canvas canvas) {
    final fill = Paint()
      ..color = AppColors.indigoSoft.withValues(alpha: 0.72)
      ..style = PaintingStyle.fill;
    final outline = Paint()
      ..color = AppColors.indigo.withValues(alpha: 0.55)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    final bench = RRect.fromRectAndRadius(
      const Rect.fromLTWH(52, 2, 46, 142),
      const Radius.circular(13),
    );
    canvas
      ..drawRRect(bench, fill)
      ..drawRRect(bench, outline)
      ..drawLine(const Offset(56, 82), const Offset(94, 82), outline);
  }

  void _drawRowSupport(Canvas canvas) {
    final fill = Paint()
      ..color = AppColors.indigoSoft.withValues(alpha: 0.8)
      ..style = PaintingStyle.fill;
    final outline = Paint()
      ..color = AppColors.indigo.withValues(alpha: 0.55)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    final pad = RRect.fromRectAndRadius(
      const Rect.fromLTWH(38, 89, 35, 7),
      const Radius.circular(3),
    );
    canvas
      ..drawRRect(pad, fill)
      ..drawRRect(pad, outline)
      ..drawLine(const Offset(43, 96), const Offset(40, 128), outline)
      ..drawLine(const Offset(68, 96), const Offset(72, 128), outline);
  }

  void _drawBody(Canvas canvas, _Pose pose, {bool ghost = false}) {
    final alpha = ghost ? 0.14 : 1.0;
    final bodyFill = Paint()
      ..color = const Color(0xFFE7EBF2).withValues(alpha: alpha)
      ..style = PaintingStyle.fill;
    final limbFill = Paint()
      ..color = const Color(0xFFD9DFE9).withValues(alpha: alpha)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 7.5
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final outline = Paint()
      ..color = AppColors.ink.withValues(alpha: ghost ? 0.12 : 0.72)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.35
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    final torso = Path()
      ..moveTo(pose.leftShoulder.dx, pose.leftShoulder.dy)
      ..quadraticBezierTo(
        pose.neck.dx,
        pose.neck.dy + 2,
        pose.rightShoulder.dx,
        pose.rightShoulder.dy,
      )
      ..lineTo(pose.rightHip.dx, pose.rightHip.dy)
      ..quadraticBezierTo(
        pose.hipCenter.dx,
        pose.hipCenter.dy + 5,
        pose.leftHip.dx,
        pose.leftHip.dy,
      )
      ..close();
    canvas
      ..drawPath(torso, bodyFill)
      ..drawPath(torso, outline);

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
      canvas
        ..drawLine(segment.$1, segment.$2, limbFill)
        ..drawLine(segment.$1, segment.$2, outline);
    }
    canvas
      ..drawLine(pose.head.translate(0, 8), pose.neck, limbFill)
      ..drawLine(pose.head.translate(0, 8), pose.neck, outline)
      ..drawCircle(pose.head, 9.5, bodyFill)
      ..drawCircle(pose.head, 9.5, outline);

    final joint = Paint()
      ..color = AppColors.surface.withValues(alpha: ghost ? 0.3 : 0.96)
      ..style = PaintingStyle.fill;
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
        ..drawCircle(point, 2.7, joint)
        ..drawCircle(point, 2.7, outline);
    }
    if (!ghost) {
      final face = Paint()
        ..color = AppColors.ink.withValues(alpha: 0.48)
        ..strokeWidth = 1
        ..strokeCap = StrokeCap.round;
      canvas
        ..drawCircle(pose.head.translate(-3, -1), 0.8, face)
        ..drawCircle(pose.head.translate(3, -1), 0.8, face)
        ..drawLine(
          pose.head.translate(-2.5, 3),
          pose.head.translate(2.5, 3),
          face,
        );
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
      ..color = color.withValues(alpha: 0.88)
      ..style = PaintingStyle.stroke
      ..strokeWidth = width
      ..strokeCap = StrokeCap.round;
    final fill = Paint()
      ..color = color.withValues(alpha: 0.68)
      ..style = PaintingStyle.fill;
    bool has(Iterable<String> names) => muscles.any(names.contains);

    if (has(const ['chest', 'pectorals'])) {
      canvas
        ..drawOval(
          Rect.fromCenter(
            center: pose.chest.translate(-6, -3),
            width: 11,
            height: 11,
          ),
          fill,
        )
        ..drawOval(
          Rect.fromCenter(
            center: pose.chest.translate(6, -3),
            width: 11,
            height: 11,
          ),
          fill,
        );
    }
    if (has(const ['back', 'lats', 'latissimus'])) {
      final back = Path()
        ..moveTo(pose.leftShoulder.dx + 2, pose.leftShoulder.dy + 4)
        ..lineTo(pose.rightShoulder.dx - 2, pose.rightShoulder.dy + 4)
        ..lineTo(pose.rightHip.dx, pose.rightHip.dy - 5)
        ..lineTo(pose.leftHip.dx, pose.leftHip.dy - 5)
        ..close();
      canvas.drawPath(back, fill);
    }
    if (has(const ['shoulders', 'deltoids', 'trapezius'])) {
      canvas
        ..drawCircle(pose.leftShoulder, width * 0.65, fill)
        ..drawCircle(pose.rightShoulder, width * 0.65, fill);
      if (has(const ['trapezius'])) {
        canvas.drawLine(pose.neck, pose.chest.translate(0, 5), paint);
      }
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
      for (final y in [-7.0, 0.0, 7.0]) {
        canvas.drawRRect(
          RRect.fromRectAndRadius(
            Rect.fromCenter(
              center: pose.core.translate(0, y),
              width: 14,
              height: 5.5,
            ),
            const Radius.circular(2.5),
          ),
          fill,
        );
      }
    }
    if (has(const ['gluteus', 'glutes', 'hip_flexors'])) {
      canvas
        ..drawCircle(pose.leftHip, width * 0.58, fill)
        ..drawCircle(pose.rightHip, width * 0.58, fill);
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
    if (kind == ExerciseMotionKind.pullUp) {
      canvas
        ..drawLine(const Offset(38, 8), const Offset(112, 8), line)
        ..drawLine(const Offset(42, 4), const Offset(42, 14), line)
        ..drawLine(const Offset(108, 4), const Offset(108, 14), line);
      if (equipment == 'bodyweight') return;
    }

    if (equipment == 'barbell') {
      final y = kind == ExerciseMotionKind.squat
          ? (pose.leftShoulder.dy + pose.rightShoulder.dy) / 2 - 2
          : (pose.leftHand.dy + pose.rightHand.dy) / 2;
      canvas.drawLine(Offset(38, y), Offset(112, y), line);
      for (final x in const [35.0, 39.0, 111.0, 115.0]) {
        canvas.drawLine(Offset(x, y - 6), Offset(x, y + 6), line);
      }
    } else if (equipment == 'dumbbell') {
      final hands = kind == ExerciseMotionKind.singleArmRow
          ? [pose.rightHand]
          : [pose.leftHand, pose.rightHand];
      for (final hand in hands) {
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
      void drawTower(double x, Offset hand, {required double pulleyY}) {
        canvas
          ..drawLine(Offset(x, 18), Offset(x, 134), line)
          ..drawLine(Offset(x - 7, 134), Offset(x + 7, 134), line)
          ..drawCircle(Offset(x, pulleyY), 4, line)
          ..drawRRect(
            RRect.fromRectAndRadius(
              Rect.fromLTWH(x - 4, 92, 8, 28),
              const Radius.circular(2),
            ),
            line,
          )
          ..drawLine(Offset(x, pulleyY), hand, line)
          ..drawLine(hand.translate(-3, 0), hand.translate(3, 0), line);
      }

      final pulleyY = switch (kind) {
        ExerciseMotionKind.lowToHighFly ||
        ExerciseMotionKind.singleArmLateralRaise ||
        ExerciseMotionKind.curl ||
        ExerciseMotionKind.hipExtension ||
        ExerciseMotionKind.hipAbduction ||
        ExerciseMotionKind.overheadExtension => 120.0,
        ExerciseMotionKind.chestFly ||
        ExerciseMotionKind.seatedRow ||
        ExerciseMotionKind.facePull ||
        ExerciseMotionKind.horizontalPush ||
        ExerciseMotionKind.horizontalPull => 52.0,
        _ => 23.0,
      };
      if (kind == ExerciseMotionKind.chestFly ||
          kind == ExerciseMotionKind.lowToHighFly) {
        drawTower(14, pose.leftHand, pulleyY: pulleyY);
        drawTower(136, pose.rightHand, pulleyY: pulleyY);
      } else {
        drawTower(136, pose.rightHand, pulleyY: pulleyY);
      }
    }
  }

  void _drawMotionGuide(
    Canvas canvas,
    _Pose pose,
    ExerciseMotionKind kind,
    double progress,
  ) {
    final guide = Paint()
      ..color = AppColors.mint.withValues(alpha: 0.9)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.2
      ..strokeCap = StrokeCap.round;
    final marker = Paint()
      ..color = AppColors.mint
      ..style = PaintingStyle.fill;

    if (kind == ExerciseMotionKind.plank) {
      final shoulder = Offset(
        (pose.leftShoulder.dx + pose.rightShoulder.dx) / 2,
        (pose.leftShoulder.dy + pose.rightShoulder.dy) / 2,
      );
      final ankle = Offset(
        (pose.leftAnkle.dx + pose.rightAnkle.dx) / 2,
        (pose.leftAnkle.dy + pose.rightAnkle.dy) / 2,
      );
      canvas
        ..drawLine(shoulder, ankle, guide)
        ..drawCircle(pose.core, 2.6 + progress * 1.2, marker);
      return;
    }

    if (kind == ExerciseMotionKind.lateralRaise) {
      final path = anatomyLateralRaiseMotionPath();
      _drawStraightArrow(
        canvas,
        path.leftStart,
        path.leftEnd,
        progress,
        guide,
        marker,
      );
      _drawStraightArrow(
        canvas,
        path.rightStart,
        path.rightEnd,
        progress,
        guide,
        marker,
      );
      return;
    }

    if (kind == ExerciseMotionKind.singleArmLateralRaise) {
      final start = _poseAt(kind, 0).rightHand;
      final end = _poseAt(kind, 1).rightHand;
      _drawStraightArrow(canvas, start, end, progress, guide, marker);
      return;
    }

    if (kind == ExerciseMotionKind.singleArmRow) {
      final start = _poseAt(kind, 0).rightHand;
      final end = _poseAt(kind, 1).rightHand;
      _drawStraightArrow(canvas, start, end, progress, guide, marker);
      return;
    }

    if (kind == ExerciseMotionKind.chestFly ||
        kind == ExerciseMotionKind.lowToHighFly ||
        kind == ExerciseMotionKind.reverseFly) {
      final path = anatomyBilateralMotionPath(kind);
      _drawCurvedArrow(
        canvas,
        path.leftStart,
        path.leftEnd,
        progress,
        guide,
        marker,
      );
      _drawCurvedArrow(
        canvas,
        path.rightStart,
        path.rightEnd,
        progress,
        guide,
        marker,
      );
      return;
    }

    final isBilateral = switch (kind) {
      ExerciseMotionKind.benchPress ||
      ExerciseMotionKind.horizontalPush ||
      ExerciseMotionKind.bentOverRow ||
      ExerciseMotionKind.seatedRow ||
      ExerciseMotionKind.facePull ||
      ExerciseMotionKind.horizontalPull ||
      ExerciseMotionKind.verticalPush ||
      ExerciseMotionKind.straightArmPulldown ||
      ExerciseMotionKind.verticalPull ||
      ExerciseMotionKind.curl ||
      ExerciseMotionKind.overheadExtension ||
      ExerciseMotionKind.elbowExtension => true,
      _ => false,
    };
    if (isBilateral) {
      final path = anatomyBilateralMotionPath(kind);
      _drawStraightArrow(
        canvas,
        path.leftStart,
        path.leftEnd,
        progress,
        guide,
        marker,
      );
      _drawStraightArrow(
        canvas,
        path.rightStart,
        path.rightEnd,
        progress,
        guide,
        marker,
      );
      return;
    }

    final start = _motionPoint(_poseAt(kind, 0), kind);
    final end = _motionPoint(_poseAt(kind, 1), kind);
    _drawStraightArrow(canvas, start, end, progress, guide, marker);
  }

  void _drawStraightArrow(
    Canvas canvas,
    Offset start,
    Offset end,
    double progress,
    Paint guide,
    Paint marker,
  ) {
    final target = Offset.lerp(start, end, progress)!;
    canvas
      ..drawLine(start, end, guide)
      ..drawCircle(target, 3.2, marker);

    final direction = end - start;
    if (direction.distance <= 2) return;
    final unit = direction / direction.distance;
    final perpendicular = Offset(-unit.dy, unit.dx);
    final arrowBase = end - unit * 8;
    canvas
      ..drawLine(end, arrowBase + perpendicular * 4, guide)
      ..drawLine(end, arrowBase - perpendicular * 4, guide);
  }

  void _drawCurvedArrow(
    Canvas canvas,
    Offset start,
    Offset end,
    double progress,
    Paint guide,
    Paint marker,
  ) {
    final control = Offset(
      (start.dx + end.dx) / 2,
      (start.dy < end.dy ? start.dy : end.dy) - 12,
    );
    final path = Path()
      ..moveTo(start.dx, start.dy)
      ..quadraticBezierTo(control.dx, control.dy, end.dx, end.dy);
    canvas.drawPath(path, guide);

    final inverse = 1 - progress;
    final target = Offset(
      inverse * inverse * start.dx +
          2 * inverse * progress * control.dx +
          progress * progress * end.dx,
      inverse * inverse * start.dy +
          2 * inverse * progress * control.dy +
          progress * progress * end.dy,
    );
    canvas.drawCircle(target, 3.2, marker);

    final tangent = end - control;
    if (tangent.distance <= 2) return;
    final unit = tangent / tangent.distance;
    final perpendicular = Offset(-unit.dy, unit.dx);
    final arrowBase = end - unit * 8;
    canvas
      ..drawLine(end, arrowBase + perpendicular * 4, guide)
      ..drawLine(end, arrowBase - perpendicular * 4, guide);
  }

  Offset _motionPoint(_Pose pose, ExerciseMotionKind kind) => switch (kind) {
    ExerciseMotionKind.squat || ExerciseMotionKind.lunge => pose.hipCenter,
    ExerciseMotionKind.hinge ||
    ExerciseMotionKind.pushUp ||
    ExerciseMotionKind.pullUp ||
    ExerciseMotionKind.kneelingCrunch ||
    ExerciseMotionKind.core => pose.chest,
    ExerciseMotionKind.gluteBridge => pose.hipCenter,
    ExerciseMotionKind.hipExtension ||
    ExerciseMotionKind.hipAbduction => pose.rightAnkle,
    ExerciseMotionKind.benchPress ||
    ExerciseMotionKind.singleArmRow ||
    ExerciseMotionKind.bentOverRow ||
    ExerciseMotionKind.seatedRow ||
    ExerciseMotionKind.facePull ||
    ExerciseMotionKind.straightArmPulldown ||
    ExerciseMotionKind.overheadExtension ||
    ExerciseMotionKind.singleArmLateralRaise ||
    ExerciseMotionKind.lowToHighFly ||
    ExerciseMotionKind.horizontalPush ||
    ExerciseMotionKind.horizontalPull ||
    ExerciseMotionKind.lateralRaise ||
    ExerciseMotionKind.chestFly ||
    ExerciseMotionKind.reverseFly ||
    ExerciseMotionKind.rotation => pose.rightHand,
    ExerciseMotionKind.plank => pose.core,
    _ => Offset(
      (pose.leftHand.dx + pose.rightHand.dx) / 2,
      (pose.leftHand.dy + pose.rightHand.dy) / 2,
    ),
  };

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
    ExerciseMotionKind.benchPress => _poseAt(
      ExerciseMotionKind.horizontalPush,
      1,
    ),
    ExerciseMotionKind.horizontalPush => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(53, 48),
      rightElbow: Offset(97, 48),
      leftHand: Offset(69, 43),
      rightHand: Offset(81, 43),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.singleArmRow => const _Pose(
      head: Offset(103, 45),
      neck: Offset(93, 52),
      leftShoulder: Offset(80, 53),
      rightShoulder: Offset(102, 61),
      leftElbow: Offset(65, 69),
      rightElbow: Offset(96, 78),
      leftHand: Offset(55, 91),
      rightHand: Offset(93, 87),
      leftHip: Offset(67, 80),
      rightHip: Offset(84, 80),
      leftKnee: Offset(64, 108),
      rightKnee: Offset(85, 108),
      leftAnkle: Offset(62, 138),
      rightAnkle: Offset(87, 138),
    ),
    ExerciseMotionKind.bentOverRow => const _Pose(
      head: Offset(103, 45),
      neck: Offset(93, 52),
      leftShoulder: Offset(80, 53),
      rightShoulder: Offset(102, 61),
      leftElbow: Offset(70, 72),
      rightElbow: Offset(96, 78),
      leftHand: Offset(73, 83),
      rightHand: Offset(93, 87),
      leftHip: Offset(67, 80),
      rightHip: Offset(84, 80),
      leftKnee: Offset(64, 108),
      rightKnee: Offset(85, 108),
      leftAnkle: Offset(62, 138),
      rightAnkle: Offset(87, 138),
    ),
    ExerciseMotionKind.seatedRow => const _Pose(
      head: Offset(75, 24),
      neck: Offset(75, 38),
      leftShoulder: Offset(60, 48),
      rightShoulder: Offset(90, 48),
      leftElbow: Offset(47, 57),
      rightElbow: Offset(103, 57),
      leftHand: Offset(62, 68),
      rightHand: Offset(88, 68),
      leftHip: Offset(67, 86),
      rightHip: Offset(83, 86),
      leftKnee: Offset(50, 108),
      rightKnee: Offset(100, 108),
      leftAnkle: Offset(43, 138),
      rightAnkle: Offset(107, 138),
    ),
    ExerciseMotionKind.facePull => const _Pose(
      head: Offset(75, 16),
      neck: Offset(75, 30),
      leftShoulder: Offset(60, 40),
      rightShoulder: Offset(90, 40),
      leftElbow: Offset(38, 43),
      rightElbow: Offset(112, 43),
      leftHand: Offset(57, 30),
      rightHand: Offset(93, 30),
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
    ExerciseMotionKind.straightArmPulldown => const _Pose(
      head: Offset(75, 17),
      neck: Offset(75, 31),
      leftShoulder: Offset(60, 41),
      rightShoulder: Offset(90, 41),
      leftElbow: Offset(57, 65),
      rightElbow: Offset(93, 65),
      leftHand: Offset(54, 89),
      rightHand: Offset(96, 89),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.pullUp => _poseAt(ExerciseMotionKind.verticalPull, 1),
    ExerciseMotionKind.verticalPull => const _Pose(
      head: Offset(75, 18),
      neck: Offset(75, 31),
      leftShoulder: Offset(60, 41),
      rightShoulder: Offset(90, 41),
      leftElbow: Offset(45, 43),
      rightElbow: Offset(105, 43),
      leftHand: Offset(61, 47),
      rightHand: Offset(89, 47),
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
    ExerciseMotionKind.overheadExtension => const _Pose(
      head: Offset(75, 20),
      neck: Offset(75, 34),
      leftShoulder: Offset(60, 43),
      rightShoulder: Offset(90, 43),
      leftElbow: Offset(55, 20),
      rightElbow: Offset(95, 20),
      leftHand: Offset(64, 4),
      rightHand: Offset(86, 4),
      leftHip: Offset(67, 80),
      rightHip: Offset(83, 80),
      leftKnee: Offset(66, 109),
      rightKnee: Offset(84, 109),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.elbowExtension => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(56, 63),
      rightElbow: Offset(94, 63),
      leftHand: Offset(55, 89),
      rightHand: Offset(95, 89),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.lateralRaise => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(39, 42),
      rightElbow: Offset(111, 42),
      leftHand: Offset(18, 43),
      rightHand: Offset(132, 43),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.singleArmLateralRaise => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(55, 64),
      rightElbow: Offset(111, 42),
      leftHand: Offset(53, 86),
      rightHand: Offset(132, 43),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.chestFly => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(56, 48),
      rightElbow: Offset(94, 48),
      leftHand: Offset(70, 48),
      rightHand: Offset(80, 48),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.lowToHighFly => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(58, 49),
      rightElbow: Offset(92, 49),
      leftHand: Offset(68, 40),
      rightHand: Offset(82, 40),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.reverseFly => const _Pose(
      head: Offset(102, 43),
      neck: Offset(92, 50),
      leftShoulder: Offset(79, 52),
      rightShoulder: Offset(101, 59),
      leftElbow: Offset(55, 60),
      rightElbow: Offset(111, 69),
      leftHand: Offset(31, 67),
      rightHand: Offset(132, 75),
      leftHip: Offset(67, 80),
      rightHip: Offset(84, 80),
      leftKnee: Offset(64, 108),
      rightKnee: Offset(85, 108),
      leftAnkle: Offset(62, 138),
      rightAnkle: Offset(87, 138),
    ),
    ExerciseMotionKind.hipExtension => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(55, 64),
      rightElbow: Offset(104, 55),
      leftHand: Offset(53, 86),
      rightHand: Offset(123, 46),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(102, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(121, 130),
    ),
    ExerciseMotionKind.hipAbduction => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(55, 64),
      rightElbow: Offset(104, 55),
      leftHand: Offset(53, 86),
      rightHand: Offset(123, 46),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(108, 105),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(131, 129),
    ),
    ExerciseMotionKind.rotation => const _Pose(
      head: Offset(71, 18),
      neck: Offset(72, 31),
      leftShoulder: Offset(57, 43),
      rightShoulder: Offset(87, 38),
      leftElbow: Offset(50, 68),
      rightElbow: Offset(67, 70),
      leftHand: Offset(44, 91),
      rightHand: Offset(55, 94),
      leftHip: Offset(66, 79),
      rightHip: Offset(84, 79),
      leftKnee: Offset(65, 108),
      rightKnee: Offset(85, 108),
      leftAnkle: Offset(63, 138),
      rightAnkle: Offset(87, 138),
    ),
    ExerciseMotionKind.pushUp => const _Pose(
      head: Offset(118, 57),
      neck: Offset(107, 62),
      leftShoulder: Offset(96, 66),
      rightShoulder: Offset(100, 69),
      leftElbow: Offset(92, 94),
      rightElbow: Offset(104, 94),
      leftHand: Offset(90, 123),
      rightHand: Offset(104, 123),
      leftHip: Offset(62, 82),
      rightHip: Offset(66, 85),
      leftKnee: Offset(40, 91),
      rightKnee: Offset(44, 94),
      leftAnkle: Offset(18, 100),
      rightAnkle: Offset(22, 103),
    ),
    ExerciseMotionKind.plank => const _Pose(
      head: Offset(118, 68),
      neck: Offset(107, 72),
      leftShoulder: Offset(96, 75),
      rightShoulder: Offset(100, 78),
      leftElbow: Offset(90, 101),
      rightElbow: Offset(102, 103),
      leftHand: Offset(112, 104),
      rightHand: Offset(119, 106),
      leftHip: Offset(62, 86),
      rightHip: Offset(66, 89),
      leftKnee: Offset(40, 94),
      rightKnee: Offset(44, 97),
      leftAnkle: Offset(18, 102),
      rightAnkle: Offset(22, 105),
    ),
    ExerciseMotionKind.gluteBridge => const _Pose(
      head: Offset(122, 106),
      neck: Offset(110, 105),
      leftShoulder: Offset(99, 102),
      rightShoulder: Offset(102, 106),
      leftElbow: Offset(88, 116),
      rightElbow: Offset(91, 120),
      leftHand: Offset(75, 121),
      rightHand: Offset(79, 124),
      leftHip: Offset(64, 70),
      rightHip: Offset(69, 73),
      leftKnee: Offset(43, 84),
      rightKnee: Offset(47, 87),
      leftAnkle: Offset(24, 121),
      rightAnkle: Offset(30, 123),
    ),
    ExerciseMotionKind.kneelingCrunch => const _Pose(
      head: Offset(83, 54),
      neck: Offset(77, 64),
      leftShoulder: Offset(63, 68),
      rightShoulder: Offset(88, 72),
      leftElbow: Offset(51, 55),
      rightElbow: Offset(98, 60),
      leftHand: Offset(62, 43),
      rightHand: Offset(90, 47),
      leftHip: Offset(67, 86),
      rightHip: Offset(83, 86),
      leftKnee: Offset(58, 112),
      rightKnee: Offset(91, 112),
      leftAnkle: Offset(51, 135),
      rightAnkle: Offset(98, 135),
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
  final start = switch (kind) {
    ExerciseMotionKind.benchPress ||
    ExerciseMotionKind.horizontalPush ||
    ExerciseMotionKind.chestFly => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(41, 47),
      rightElbow: Offset(109, 47),
      leftHand: Offset(21, 47),
      rightHand: Offset(129, 47),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.singleArmRow => const _Pose(
      head: Offset(104, 45),
      neck: Offset(94, 52),
      leftShoulder: Offset(81, 51),
      rightShoulder: Offset(103, 60),
      leftElbow: Offset(65, 69),
      rightElbow: Offset(104, 84),
      leftHand: Offset(55, 91),
      rightHand: Offset(102, 105),
      leftHip: Offset(67, 79),
      rightHip: Offset(84, 80),
      leftKnee: Offset(64, 107),
      rightKnee: Offset(85, 108),
      leftAnkle: Offset(62, 138),
      rightAnkle: Offset(87, 138),
    ),
    ExerciseMotionKind.bentOverRow => const _Pose(
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
    ExerciseMotionKind.seatedRow => const _Pose(
      head: Offset(75, 24),
      neck: Offset(75, 38),
      leftShoulder: Offset(60, 48),
      rightShoulder: Offset(90, 48),
      leftElbow: Offset(63, 62),
      rightElbow: Offset(87, 62),
      leftHand: Offset(70, 68),
      rightHand: Offset(80, 68),
      leftHip: Offset(67, 86),
      rightHip: Offset(83, 86),
      leftKnee: Offset(50, 108),
      rightKnee: Offset(100, 108),
      leftAnkle: Offset(43, 138),
      rightAnkle: Offset(107, 138),
    ),
    ExerciseMotionKind.facePull => const _Pose(
      head: Offset(75, 16),
      neck: Offset(75, 30),
      leftShoulder: Offset(60, 40),
      rightShoulder: Offset(90, 40),
      leftElbow: Offset(61, 48),
      rightElbow: Offset(89, 48),
      leftHand: Offset(70, 40),
      rightHand: Offset(80, 40),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.straightArmPulldown => const _Pose(
      head: Offset(75, 17),
      neck: Offset(75, 31),
      leftShoulder: Offset(60, 41),
      rightShoulder: Offset(90, 41),
      leftElbow: Offset(56, 25),
      rightElbow: Offset(94, 25),
      leftHand: Offset(55, 7),
      rightHand: Offset(95, 7),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.lowToHighFly => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(42, 69),
      rightElbow: Offset(108, 69),
      leftHand: Offset(20, 91),
      rightHand: Offset(130, 91),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.reverseFly => const _Pose(
      head: Offset(102, 43),
      neck: Offset(92, 50),
      leftShoulder: Offset(79, 52),
      rightShoulder: Offset(101, 59),
      leftElbow: Offset(82, 67),
      rightElbow: Offset(101, 72),
      leftHand: Offset(84, 83),
      rightHand: Offset(99, 86),
      leftHip: Offset(67, 80),
      rightHip: Offset(84, 80),
      leftKnee: Offset(64, 108),
      rightKnee: Offset(85, 108),
      leftAnkle: Offset(62, 138),
      rightAnkle: Offset(87, 138),
    ),
    ExerciseMotionKind.verticalPush => const _Pose(
      head: Offset(75, 18),
      neck: Offset(75, 31),
      leftShoulder: Offset(60, 41),
      rightShoulder: Offset(90, 41),
      leftElbow: Offset(48, 56),
      rightElbow: Offset(102, 56),
      leftHand: Offset(59, 48),
      rightHand: Offset(91, 48),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.pullUp || ExerciseMotionKind.verticalPull => const _Pose(
      head: Offset(75, 18),
      neck: Offset(75, 31),
      leftShoulder: Offset(60, 41),
      rightShoulder: Offset(90, 41),
      leftElbow: Offset(58, 22),
      rightElbow: Offset(92, 22),
      leftHand: Offset(62, 5),
      rightHand: Offset(88, 5),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.overheadExtension => const _Pose(
      head: Offset(75, 20),
      neck: Offset(75, 34),
      leftShoulder: Offset(60, 43),
      rightShoulder: Offset(90, 43),
      leftElbow: Offset(55, 20),
      rightElbow: Offset(95, 20),
      leftHand: Offset(68, 31),
      rightHand: Offset(82, 31),
      leftHip: Offset(67, 80),
      rightHip: Offset(83, 80),
      leftKnee: Offset(66, 109),
      rightKnee: Offset(84, 109),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.elbowExtension => const _Pose(
      head: Offset(75, 15),
      neck: Offset(75, 29),
      leftShoulder: Offset(60, 39),
      rightShoulder: Offset(90, 39),
      leftElbow: Offset(56, 63),
      rightElbow: Offset(94, 63),
      leftHand: Offset(63, 46),
      rightHand: Offset(87, 46),
      leftHip: Offset(67, 78),
      rightHip: Offset(83, 78),
      leftKnee: Offset(66, 108),
      rightKnee: Offset(84, 108),
      leftAnkle: Offset(64, 138),
      rightAnkle: Offset(86, 138),
    ),
    ExerciseMotionKind.pushUp => const _Pose(
      head: Offset(118, 75),
      neck: Offset(107, 79),
      leftShoulder: Offset(96, 80),
      rightShoulder: Offset(100, 84),
      leftElbow: Offset(92, 105),
      rightElbow: Offset(104, 106),
      leftHand: Offset(90, 123),
      rightHand: Offset(104, 123),
      leftHip: Offset(62, 87),
      rightHip: Offset(66, 90),
      leftKnee: Offset(40, 92),
      rightKnee: Offset(44, 95),
      leftAnkle: Offset(18, 100),
      rightAnkle: Offset(22, 103),
    ),
    ExerciseMotionKind.plank => const _Pose(
      head: Offset(118, 68),
      neck: Offset(107, 72),
      leftShoulder: Offset(96, 75),
      rightShoulder: Offset(100, 78),
      leftElbow: Offset(90, 101),
      rightElbow: Offset(102, 103),
      leftHand: Offset(112, 104),
      rightHand: Offset(119, 106),
      leftHip: Offset(62, 86),
      rightHip: Offset(66, 89),
      leftKnee: Offset(40, 94),
      rightKnee: Offset(44, 97),
      leftAnkle: Offset(18, 102),
      rightAnkle: Offset(22, 105),
    ),
    ExerciseMotionKind.gluteBridge => const _Pose(
      head: Offset(122, 106),
      neck: Offset(110, 105),
      leftShoulder: Offset(99, 102),
      rightShoulder: Offset(102, 106),
      leftElbow: Offset(88, 116),
      rightElbow: Offset(91, 120),
      leftHand: Offset(75, 121),
      rightHand: Offset(79, 124),
      leftHip: Offset(65, 108),
      rightHip: Offset(70, 111),
      leftKnee: Offset(43, 84),
      rightKnee: Offset(47, 87),
      leftAnkle: Offset(24, 121),
      rightAnkle: Offset(30, 123),
    ),
    ExerciseMotionKind.kneelingCrunch => const _Pose(
      head: Offset(75, 25),
      neck: Offset(75, 39),
      leftShoulder: Offset(60, 45),
      rightShoulder: Offset(90, 45),
      leftElbow: Offset(48, 45),
      rightElbow: Offset(102, 45),
      leftHand: Offset(61, 34),
      rightHand: Offset(89, 34),
      leftHip: Offset(67, 86),
      rightHip: Offset(83, 86),
      leftKnee: Offset(58, 112),
      rightKnee: Offset(91, 112),
      leftAnkle: Offset(51, 135),
      rightAnkle: Offset(98, 135),
    ),
    ExerciseMotionKind.rotation => const _Pose(
      head: Offset(79, 17),
      neck: Offset(78, 30),
      leftShoulder: Offset(63, 38),
      rightShoulder: Offset(93, 43),
      leftElbow: Offset(84, 34),
      rightElbow: Offset(104, 44),
      leftHand: Offset(99, 31),
      rightHand: Offset(113, 39),
      leftHip: Offset(66, 79),
      rightHip: Offset(84, 79),
      leftKnee: Offset(65, 108),
      rightKnee: Offset(85, 108),
      leftAnkle: Offset(63, 138),
      rightAnkle: Offset(87, 138),
    ),
    _ => _neutralPose,
  };
  final breathing = kind == ExerciseMotionKind.generic
      ? (0.03 * progress)
      : 0.0;
  final pose = _Pose.lerp(start, target, progress);
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

({Offset leftStart, Offset leftEnd, Offset rightStart, Offset rightEnd})
anatomyFlyMotionPath(ExerciseMotionKind kind) {
  assert(
    kind == ExerciseMotionKind.chestFly ||
        kind == ExerciseMotionKind.reverseFly,
  );
  return anatomyBilateralMotionPath(kind);
}

({Offset leftStart, Offset leftEnd, Offset rightStart, Offset rightEnd})
anatomyBilateralMotionPath(ExerciseMotionKind kind) {
  final start = _poseAt(kind, 0);
  final end = _poseAt(kind, 1);
  return (
    leftStart: start.leftHand,
    leftEnd: end.leftHand,
    rightStart: start.rightHand,
    rightEnd: end.rightHand,
  );
}

({Offset leftStart, Offset leftEnd, Offset rightStart, Offset rightEnd})
anatomyLateralRaiseMotionPath() {
  final start = _poseAt(ExerciseMotionKind.lateralRaise, 0);
  final end = _poseAt(ExerciseMotionKind.lateralRaise, 1);
  return (
    leftStart: start.leftHand,
    leftEnd: end.leftHand,
    rightStart: start.rightHand,
    rightEnd: end.rightHand,
  );
}

String _stageLabel(ExerciseMotionKind kind, double progress) {
  final isStart = progress < 0.48;
  return switch (kind) {
    ExerciseMotionKind.chestFly => isStart ? '两侧打开 · 起始' : '向胸前夹合 · 发力',
    ExerciseMotionKind.reverseFly => isStart ? '胸前合拢 · 起始' : '向两侧打开 · 发力',
    ExerciseMotionKind.lateralRaise => isStart ? '大腿两侧 · 起始' : '抬至肩高 · 发力',
    ExerciseMotionKind.singleArmLateralRaise =>
      isStart ? '手柄在腿侧 · 起始' : '单臂抬至肩高 · 发力',
    ExerciseMotionKind.benchPress => isStart ? '负重降至胸侧 · 起始' : '向上推起 · 发力',
    ExerciseMotionKind.singleArmRow => isStart ? '单臂自然下垂 · 起始' : '肘部拉向髋部 · 发力',
    ExerciseMotionKind.bentOverRow => isStart ? '俯身手臂下垂 · 起始' : '肘部拉向髋部 · 发力',
    ExerciseMotionKind.seatedRow => isStart ? '手臂前伸 · 起始' : '拉向腹部 · 发力',
    ExerciseMotionKind.facePull => isStart ? '绳索在面前 · 起始' : '拉向眉眼并外旋 · 发力',
    ExerciseMotionKind.straightArmPulldown =>
      isStart ? '双臂斜上方 · 起始' : '压向大腿 · 发力',
    ExerciseMotionKind.pullUp => isStart ? '悬垂 · 起始' : '胸部靠近横杆 · 发力',
    ExerciseMotionKind.overheadExtension => isStart ? '肘部弯曲 · 起始' : '头顶伸肘 · 发力',
    ExerciseMotionKind.lowToHighFly => isStart ? '低位两侧 · 起始' : '斜上夹合 · 发力',
    ExerciseMotionKind.pushUp => isStart ? '胸部接近地面 · 起始' : '推离地面 · 发力',
    ExerciseMotionKind.plank => '保持头、髋、踝成一直线',
    ExerciseMotionKind.gluteBridge => isStart ? '髋部贴近地面 · 起始' : '夹臀抬髋 · 发力',
    ExerciseMotionKind.kneelingCrunch =>
      isStart ? '跪姿躯干展开 · 起始' : '肋骨卷向骨盆 · 发力',
    _ => isStart ? '起始位' : '发力位',
  };
}

String _directionLabel(ExerciseMotionKind kind) => switch (kind) {
  ExerciseMotionKind.chestFly => '箭头向内夹合',
  ExerciseMotionKind.reverseFly => '箭头向外打开',
  ExerciseMotionKind.lateralRaise => '箭头从腿侧向外上方',
  ExerciseMotionKind.singleArmLateralRaise => '单侧箭头向外上方',
  ExerciseMotionKind.benchPress || ExerciseMotionKind.pushUp => '箭头指向推起方向',
  ExerciseMotionKind.singleArmRow => '单侧箭头拉向髋部',
  ExerciseMotionKind.bentOverRow || ExerciseMotionKind.seatedRow => '箭头指向身体',
  ExerciseMotionKind.facePull => '箭头拉向面部两侧',
  ExerciseMotionKind.straightArmPulldown => '箭头从头顶压向大腿',
  ExerciseMotionKind.pullUp => '箭头指向身体上移',
  ExerciseMotionKind.overheadExtension => '箭头指向伸肘方向',
  ExerciseMotionKind.lowToHighFly => '箭头斜上夹向上胸',
  ExerciseMotionKind.plank => '绿线检查身体是否平直',
  ExerciseMotionKind.gluteBridge => '箭头指向抬髋方向',
  ExerciseMotionKind.kneelingCrunch => '箭头指向卷腹方向',
  _ => '绿色箭头看方向',
};

String _motionCaption(ExerciseMotionKind kind, String equipment) =>
    switch (kind) {
      ExerciseMotionKind.squat => '观察髋、膝同步屈伸',
      ExerciseMotionKind.hinge => '观察髋部后移与躯干前倾',
      ExerciseMotionKind.lunge => '观察前后腿协同和重心下降',
      ExerciseMotionKind.benchPress => '俯视：负重从胸部两侧推向上方',
      ExerciseMotionKind.horizontalPush => '观察手臂水平推出轨迹',
      ExerciseMotionKind.singleArmRow => '支撑侧保持稳定，单侧肘部沿躯干拉向髋部',
      ExerciseMotionKind.bentOverRow => '保持俯身，肘部沿躯干拉向髋部',
      ExerciseMotionKind.seatedRow => '坐稳后将手柄拉向腹部',
      ExerciseMotionKind.facePull => '绳索拉向眉眼，同时向两侧分开',
      ExerciseMotionKind.horizontalPull => '观察肘部向后收紧轨迹',
      ExerciseMotionKind.verticalPush => '观察手臂垂直推举轨迹',
      ExerciseMotionKind.straightArmPulldown => '肘部近乎固定，手柄从头顶压向大腿',
      ExerciseMotionKind.pullUp => '从悬垂位将身体拉向横杆',
      ExerciseMotionKind.verticalPull => '观察肩胛下沉与肘部下拉',
      ExerciseMotionKind.curl => '观察肘关节屈伸轨迹',
      ExerciseMotionKind.overheadExtension => '固定上臂，在头顶完成伸肘',
      ExerciseMotionKind.elbowExtension => '观察肘部固定与前臂伸展',
      ExerciseMotionKind.lateralRaise => '双手从大腿两侧向外抬至肩高',
      ExerciseMotionKind.singleArmLateralRaise => '单手从大腿侧方沿绳索阻力抬至肩高',
      ExerciseMotionKind.chestFly =>
        equipment == 'dumbbell' ? '俯视：双臂从两侧向胸部上方夹合' : '双臂从两侧向胸前夹合',
      ExerciseMotionKind.lowToHighFly => '双手从低位两侧沿弧线夹向上胸',
      ExerciseMotionKind.reverseFly => '双臂从胸前向两侧打开，后束发力',
      ExerciseMotionKind.hipExtension => '观察髋部伸展与臀肌收缩',
      ExerciseMotionKind.hipAbduction => '观察腿部向外打开轨迹',
      ExerciseMotionKind.rotation => '观察躯干与髋部协同旋转',
      ExerciseMotionKind.pushUp => '侧视：身体保持直线并推离地面',
      ExerciseMotionKind.plank => '侧视：持续收紧核心，避免塌腰或抬髋',
      ExerciseMotionKind.gluteBridge => '侧视：脚掌踩稳，夹臀将髋部抬起',
      ExerciseMotionKind.kneelingCrunch => '保持髋部稳定，将肋骨卷向骨盆',
      ExerciseMotionKind.core => '观察躯干稳定与屈曲轨迹',
      ExerciseMotionKind.generic => '观察关节轨迹与主要发力区域',
    };

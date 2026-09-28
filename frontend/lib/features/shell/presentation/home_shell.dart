import 'package:flutter/material.dart';

import '../../../core/media/image_upload.dart';
import '../../../core/theme/app_theme.dart';
import '../../agent/data/agent_repository.dart';
import '../../agent/data/proactive_repository.dart';
import '../../agent/presentation/agent_controller.dart';
import '../../agent/presentation/agent_page.dart';
import '../../agent/presentation/proactive_controller.dart';
import '../../auth/presentation/session_controller.dart';
import '../../exercises/data/exercise_repository.dart';
import '../../exercises/presentation/exercise_library_page.dart';
import '../../nutrition/data/nutrition_repository.dart';
import '../../nutrition/presentation/nutrition_controller.dart';
import '../../nutrition/presentation/nutrition_page.dart';
import '../../progress/data/body_repository.dart';
import '../../progress/data/body_progress_repository.dart';
import '../../progress/presentation/body_progress_controller.dart';
import '../../progress/presentation/body_progress_page.dart';
import '../../progress/presentation/progress_controller.dart';
import '../../progress/presentation/progress_page.dart';
import '../../profile/data/profile_repository.dart';
import '../../profile/presentation/profile_controller.dart';
import '../../profile/presentation/profile_page.dart';
import '../../training/data/training_repository.dart';
import '../../training/presentation/plan_controller.dart';
import '../../training/presentation/plan_page.dart';
import '../../training/presentation/today_page.dart';
import '../../training/presentation/training_controller.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.controller});

  final SessionController controller;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;
  late final TrainingController _trainingController;
  late final ImageUploadRepository _imageUploadRepository;
  late final AgentController _agentController;
  late final ProactiveController _proactiveController;
  late final NutritionController _nutritionController;
  late final ProgressController _progressController;
  late final BodyProgressController _bodyProgressController;
  late final PlanController _planController;
  late final ProfileController _profileController;
  late final ExerciseRepository _exerciseRepository;

  @override
  void initState() {
    super.initState();
    _trainingController = TrainingController(
      TrainingRepository(widget.controller.authRepository.apiClient),
    );
    _imageUploadRepository = ImageUploadRepository(
      widget.controller.authRepository.apiClient,
    );
    _agentController = AgentController(
      AgentRepository(widget.controller.authRepository.apiClient),
      imageUploader: _imageUploadRepository.uploadChatImage,
    );
    _proactiveController = ProactiveController(
      ProactiveRepository(widget.controller.authRepository.apiClient),
    );
    _nutritionController = NutritionController(
      NutritionRepository(widget.controller.authRepository.apiClient),
      imageUploader: _imageUploadRepository.uploadNutritionImage,
    );
    _progressController = ProgressController(
      BodyRepository(widget.controller.authRepository.apiClient),
    );
    _bodyProgressController = BodyProgressController(
      BodyProgressRepository(widget.controller.authRepository.apiClient),
      _imageUploadRepository.uploadBodyProgressImage,
    );
    _planController = PlanController(
      TrainingRepository(widget.controller.authRepository.apiClient),
      imageUploader: _imageUploadRepository.uploadTrainingPlanImage,
      profileRepository: ProfileRepository(
        widget.controller.authRepository.apiClient,
      ),
    );
    _profileController = ProfileController(
      ProfileRepository(widget.controller.authRepository.apiClient),
    );
    _exerciseRepository = ExerciseRepository(
      widget.controller.authRepository.apiClient,
    );
  }

  @override
  void dispose() {
    _trainingController.dispose();
    _agentController.dispose();
    _proactiveController.dispose();
    _imageUploadRepository.close();
    _nutritionController.dispose();
    _progressController.dispose();
    _bodyProgressController.dispose();
    _planController.dispose();
    _profileController.dispose();
    super.dispose();
  }

  void _selectTab(int value) {
    if (value == 0) {
      _trainingController.refresh();
      _proactiveController.refresh();
    }
    if (value == 1) _planController.refresh();
    if (value == 2) _nutritionController.refresh();
    if (value == 3) _progressController.refresh();
    setState(() => _index = value);
  }

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      TodayPage(
        username: widget.controller.account?.username ?? '',
        controller: _trainingController,
        proactiveController: _proactiveController,
        exerciseRepository: _exerciseRepository,
        onOpenPlan: () => _selectTab(1),
        onOpenProgress: () => _selectTab(3),
        onOpenAgent: () => _selectTab(4),
        onDiscussNotice: (notice) async {
          final prompt = switch (notice.kind) {
            'missed_workout' =>
              '昨天日历中的训练尚未标记完成。请先核对我的训练记录和日历，若需要调整，只提出草稿供我确认，不要直接修改。',
            'recovery_check' =>
              '昨天我记录了较高训练后疲劳。请先核对记录与今天安排，讨论安全的调整；如需变更，先提出草稿等我确认。',
            'nutrition_log_gap' =>
              '昨天没有饮食记录，请帮我核对，但不要假设我没有进食。如需补记或调整，请先提出草稿供我确认。',
            _ => '请根据这条主动建议先核对事实，再讨论是否需要调整；任何变更都请先提出草稿等我确认。',
          };
          _selectTab(4);
          await _agentController.send(prompt);
        },
        onOpenNutrition: () => _selectTab(2),
      ),
      PlanPage(
        controller: _planController,
        onOpenExerciseLibrary: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) =>
                ExerciseLibraryPage(repository: _exerciseRepository),
          ),
        ),
        onAskCoach: (prompt) async {
          _selectTab(4);
          await _agentController.send(prompt);
        },
      ),
      NutritionPage(controller: _nutritionController, embedded: true),
      ProgressPage(
        controller: _progressController,
        onOpenBodyProgress: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) =>
                BodyProgressPage(controller: _bodyProgressController),
          ),
        ),
      ),
      AgentPage(controller: _agentController),
      ProfilePage(
        controller: _profileController,
        username: widget.controller.account?.username ?? '',
        loggingOut: widget.controller.submitting,
        onLogout: widget.controller.logout,
      ),
    ];

    return Scaffold(
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: DecoratedBox(
        decoration: const BoxDecoration(
          color: Colors.white,
          border: Border(top: BorderSide(color: AppColors.line, width: 0.8)),
        ),
        child: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: _selectTab,
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.home_outlined),
              selectedIcon: Icon(Icons.home_rounded),
              label: '首页',
            ),
            NavigationDestination(
              icon: Icon(Icons.bolt_outlined),
              selectedIcon: Icon(Icons.bolt_rounded),
              label: '计划',
            ),
            NavigationDestination(
              icon: Icon(Icons.restaurant_menu_outlined),
              selectedIcon: Icon(Icons.restaurant_menu_rounded),
              label: '饮食',
            ),
            NavigationDestination(
              icon: Icon(Icons.insights_outlined),
              selectedIcon: Icon(Icons.insights_rounded),
              label: '进展',
            ),
            NavigationDestination(
              icon: Icon(Icons.auto_awesome_outlined),
              selectedIcon: Icon(Icons.auto_awesome_rounded),
              label: 'AI教练',
            ),
            NavigationDestination(
              icon: Icon(Icons.person_outline_rounded),
              selectedIcon: Icon(Icons.person_rounded),
              label: '我的',
            ),
          ],
        ),
      ),
    );
  }
}

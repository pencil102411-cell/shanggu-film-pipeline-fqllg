# 提示词模板

`{{...}}` 是编写时的变量，不是平台参数。按当前原片替换；没有来源的字段不能填假数。无台词、无抛接、无慢动作的素材删除相关例外。用户只提供文字分析时说明数据来源，不能标为独立测量。

默认整段生成一条剪辑成片，镜头按时间硬切。若用户指定另一个交付形态，相应改写【原片与输出】，不保留互相冲突的说明。

默认使用中文模板。用户要求英文或中英双版时，使用文末的英文模板，两版内容逐段对应，不能一版多写一版少写。

## 素材引用写法

- `{{原片标签}}`、`{{图片标签}}` 统一写半角 `(视频1)`、`(图片1)`，全文每一处引用都带括号。完整规则（编号、不省略、换到其他入口怎么改）见 `<技能目录>/../../shared/素材引用写法.md`；Scenario 作者案例写 `@video1`，见 [platform-notes.md](platform-notes.md)。以当前界面为准。
- 图片编号与平台接入顺序一致，每张接入的图片在提示词里都要被引用到，且只写一个用途。
- 「图片」「视频」两个词后面不要直接跟非编号的数字，例如把「参考视频27秒」写成「参考视频时长为27秒」。
- 【参考素材分工】只列这次实际拿到并接入的图。用户没提供的面，按 [asset-checklist.md](asset-checklist.md) 中约定的处理方式写进【新露出的区域】，不要写成“参考某图”。

## 中文模板（默认）

```text
同一场已完成的表演，换机位重新拍摄

【原片与输出】
{{原片标签}} 是时间轴母版：{{原片描述}}，时长 {{T}} 秒，{{音轨状态}}。这段表演已经发生过，请从下面的机位把同一事件重新拍一遍。不要重新调度、重新表演、重新诠释，也不要改变节奏。
输出一条覆盖 0.00–{{T}} 秒的完整单画面剪辑成片。按指定时间点在各机位之间硬切，全程沿用同一条连续的原片时间轴。不要分屏、拼贴，也不要在同一画面里同时出现多个视角。输出第 t 秒的画面，就是原片第 t 秒发生的事件。在 {{T}} 秒结束，结尾不补帧、不拖长。

【参考素材分工】
{{原片标签}}：唯一的表演、动作、口型、声音和时间轴来源。
{{人物图标签}}：只作为 {{人物}} 的 {{角度/细节}} 外观参考（如背面发型、服装背面、侧脸轮廓），不改变原片的姿态、动作和表情。
{{场景图标签}}：只作为 {{场景面名称}}（{{按原画面方位说明的方向}}）的背景参考，用于 {{机位/时间段}}。光线方向、软硬、色温和调色以原片为准，不照搬参考图里的人物、光线或天气。
{{道具图标签}}：只作为 {{道具}} 的外观细节参考，数量和位置以原片为准。
参考图之间或参考图与原片有冲突时，以原片为准。

【锁定的表演与场景】
保持原片中的人物身份、身体姿态、头部角度、原始视线、微表情、眨眼时机、嘴部动作、双手、与物体的接触、物体数量、动作路径和事件时间。保持服装、道具、场景布局、光源方向与软硬、曝光、白平衡和调色。
只允许改变机位位置、朝向、焦段感、构图、焦点、景深、摄影机运动和下面列出的切镜。透视、视差、遮挡和反光随视角自然变化。绝不为了新构图移动演员或道具。

【声音与发声窗口】
保留原片的对白、音色、停顿、环境声和声音事件，并与原片时间轴同步。不改写台词、不配音、不重新生成一段新表演，不添加音乐或音效。
{{人物}} 说话：{{核对过或用户提供的区间}}。
{{人物}} 不说话：{{互补区间及其中实际的无声口部动作}}。
有多名人物时，逐人重复以上两行。
说话期间只要能看到嘴，嘴部动作就跟原片说话一致，即使人物低头、侧脸或处于虚焦。看不到嘴时，原音照常继续。“不说话”不等于嘴巴冻结或一定闭合：保留原片的呼吸、喝水、咀嚼等无声口部动作。这些区间不要把环境声静音。

【视线】
原片表演的对象是 {{原摄影机/对手/物体及其空间位置}}。保留随时间变化的视线目标：{{原片中的瞥视与回视}}。
人物不会转向、寻找或招呼新的摄影机。{{侧面/背面/正轴机位下视线的几何说明}}。只有当原片视线与新镜头位置在同一时刻自然重合时，才出现看镜头的效果。

【播放速度】
与原片 1:1 播放。不新增慢动作、变速、定格、时间重映射、重复动作或跳时。
{{如有：原片自带的慢放段及其精确或标注精度的区间；按原样保留，不再放慢或拉长。}}

【事件锚点】
{{每个快速或依赖接触的动作：动作前的时间与物体状态；离手/接触/开始；轨迹或动作阶段；接住/结束/接触；之后的状态。}}
摄影机可以跟随这些事件，但不能改变它们的时间、路径、时长或结果。同一物体在所有镜头里始终是同一个物体。

【新露出的区域】
{{每个相关机位：有原片或参考图支撑的可见背景，并注明来源；需要避开画面的区域；不能凭空添加的具体内容；用户未提供参考时采用的处理方式。}}
各机位之间保持一致的空间关系。不要用没有依据的显眼人物、建筑、招牌或道具去填补没见过的区域。

【机位计划】
[{{起}}–{{止}}秒] {{相对人物与场景的机位位置、高度与角度}}；{{景别、焦段感}}，{{一个主要运镜及其方向/终点}}，{{焦点对象与景深}}。这一段展示原片动作：{{动作、头部/视线与物体状态}}。{{嘴部是否可见，以及与发声区间的交集}}。{{已知前景/背景（注明对应的参考素材）与必须保持的连续性}}。
{{依次写完其余相邻区间，最后一段正好结束于 T。}}

【人物与场景连续性】
{{人物身份与显著特征；服装与发型；道具身份/数量/位置；场景结构；光线与色彩锚点——全部取自本片。}}

【禁止新增】
不新增人物、动作、台词、重复物体、未要求的场景改动、字幕或对比标签。保留场景里原有的细节。{{本任务特有的排除项}}。
```

## 英文模板（用户要求英文或中英双版时使用）

```text
ONE FINISHED PERFORMANCE, RE-PHOTOGRAPHED

SOURCE AND OUTPUT
{{SOURCE_TAG}} is the timeline master: {{source description}}, duration {{T}} seconds, with {{audio status}}. The performance has already happened. Re-photograph that same event from the camera positions below. Do not restage, re-perform, reinterpret or re-time it.
Create ONE full-frame edited video covering 0.00–{{T}} seconds. Cut between the specified views at their boundaries, following one continuous source timeline. Do not create a split-screen, collage, or simultaneous views. At output time t, show the event occurring at source time t. End at {{T}}; do not pad the ending.

REFERENCE ROLES
{{SOURCE_TAG}}: the only source of performance, action, lip movement, audio and timing.
{{CHARACTER_IMAGE_TAG}}: appearance reference for {{character}} from {{angle/detail}} only; it does not change the source pose, action or expression.
{{SCENE_IMAGE_TAG}}: background reference for {{scene side}} ({{direction in original-frame terms}}) only, used in {{shots/intervals}}. Light direction, softness, colour temperature and grade follow the source; do not copy people, lighting or weather from the reference.
{{PROP_IMAGE_TAG}}: appearance reference for {{prop}} only; count and placement follow the source.
Where references conflict with each other or with the source, the source wins.

LOCKED PERFORMANCE AND WORLD
Preserve identity, body pose, head angle, original eyeline, microexpressions, blink timing, lip movement, hands, contact with objects, object count, action paths and event timings from the source. Keep wardrobe, props, set layout, light direction and softness, exposure, white balance and colour grade.
Only camera position, orientation, focal-length intention, framing, focus, depth of field, camera movement and the listed cuts may change. Perspective, parallax, occlusion and reflections must change naturally with viewpoint. Never move the actor or a prop to improve a new composition.

AUDIO AND SPEECH WINDOWS
Preserve the original dialogue, voice, pauses, ambience and sound events, synchronized to the source timeline. Do not rewrite, dub, regenerate a new performance, or add music or sound effects.
{{speaker identity}} SPEAKING: {{verified or user-supplied intervals}}.
{{speaker identity}} NO SPOKEN WORDS: {{complementary intervals with actual nonverbal mouth actions}}.
Repeat the speaker-specific map only if more speakers are present.
Whenever the mouth is visible during speech, its movements follow the original speech, even when the person looks down, appears in profile or is out of focus. When the mouth is hidden, the original audio continues. No spoken words does not mean a frozen or necessarily closed mouth: preserve the source breathing, drinking, chewing and other nonverbal movement. Do not mute ambience in these intervals.

EYELINE
The original performance is directed toward {{original camera/person/object and spatial location}}. Preserve its time-varying gaze targets: {{source glances and returns}}.
The subject does not turn toward, search for, or greet a new camera. {{geometry-specific instructions for side/rear/on-axis views}}. Lens contact occurs only where the source gaze and the new lens position naturally align at that same instant.

PLAYBACK TEMPO
Match the playback of the source 1:1. No new slow motion, speed ramps, freeze frames, time remapping, repeated actions or temporal skips.
{{If present: source-embedded slow passage and exact or qualified interval; retain it as recorded, without slowing or extending it further.}}

EVENT ANCHORS
{{For each fast or contact-critical action: time before action and object state; release/contact/start; trajectory or action phase; catch/end/contact; state afterward.}}
Camera movement may follow these events but may not change their timing, path, duration or outcome. The same object remains the same object across all cuts.

NEWLY REVEALED AREAS
{{For each relevant view: evidence-backed visible background and its source; areas to keep out of frame; specific content that must not be invented; the agreed handling where no reference was supplied.}}
Maintain a coherent space across views. Do not fill unseen areas with unsupported salient people, architecture, signage or props.

CAMERA PLAN
[{{start}}–{{end}}] {{camera position relative to subject and world, height and angle}}; {{shot size, focal-length feel}}, {{one dominant camera move with direction/end position}}, {{focus target and depth of field}}. Show the source action at this interval: {{action, head/gaze and object state}}. {{mouth visibility and intersecting speech/non-speech intervals}}. {{known foreground/background with its reference, and required continuity}}.
{{Repeat for the remaining consecutive intervals, ending exactly at T.}}

SUBJECT AND SET CONTINUITY
{{Subject identity and distinctive details; wardrobe and hair; prop identities/counts/locations; scene geometry; lighting and colour anchors, all derived from this source.}}

NO ADDITIONS
No added people, actions, dialogue, object duplicates, unrequested set changes, captions or comparison labels. Preserve source-native details that belong to the scene. {{Any task-specific exclusions.}}
```

## 信息不足时

- 时长已知、语音窗口未知：仍可写“逐时跟随源音轨与口型”，并把窗口精确表列为待核对；不编造说话时间。需要精确窗口的交付暂标草稿。
- 只有一张截图：能写视觉锁定与摄影方向，不能完成原片时间表。
- 用户提供精确事件表但无法查看原片：可以据此输出完整提示词，注明“按用户时间表编写，原片未独立核对”，不要用“实测”冒充。
- 需裁剪或独立全长机位时：统一修改【原片与输出】与每段时间映射。不能只改总时长而留下旧锚点。
- 某个场景面或人物角度没有参考图：按用户在资产索取环节选定的处理方式写（避开、浅景深虚化或最小假设），并在交付说明里列出。

音轨原样保留是交付要求。若平台生成音轨有变化或不带音轨，应在剪辑中回贴原音并验同步，不能靠追加一句提示词就宣称无损通过。

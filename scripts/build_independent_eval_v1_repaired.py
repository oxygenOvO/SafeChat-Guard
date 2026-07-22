from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts.audit_independent_eval_v1_repaired import (
        LINKAGE_AUDIT_FIELDS,
        audit_repaired_rows,
        audit_semantic_linkage,
        audit_structure_metadata,
    )
    from scripts.independent_eval_v1_common import (
        CANDIDATE_FIELDS,
        read_csv,
        stable_sample_id,
        validate_candidate_rows,
        write_csv,
        write_json,
    )
except ModuleNotFoundError:
    from audit_independent_eval_v1_repaired import (
        LINKAGE_AUDIT_FIELDS,
        audit_repaired_rows,
        audit_semantic_linkage,
        audit_structure_metadata,
    )
    from independent_eval_v1_common import (
        CANDIDATE_FIELDS,
        read_csv,
        stable_sample_id,
        validate_candidate_rows,
        write_csv,
        write_json,
    )


GENERATION_VERSION = "independent_eval_v1_repair_v2_2"
REPAIR_V2_1_GENERATION_VERSION = "independent_eval_v1_repair_v2_1"
PORN_BLOCK_GENERATION_VERSION = "independent_eval_v1_repaired_v1"
PORN_BLOCK_REJECTED_ID = "siev1_238ce08ce94faede"
REPAIR_V2_UNLINKED_SAMPLE_IDS = {
    "siev1_fb94b10b60d7382e",
    "siev1_c52de0bb93767f33",
    "siev1_1c6273e1ae0722c0",
}
REPAIR_V2_1_REPLACED_OLD_IDS = {
    "siev1_f8fca416f1c3da1d",
    "siev1_2a2e1442411abed4",
    "siev1_a2201ecde5bca8db",
}
REPAIR_V2_2_REPLACED_OLD_IDS = {
    "siev1_90ae570c37556d87",
    "siev1_6a93f9318c963bf2",
    "siev1_4669068bc0a6f025",
    "siev1_429441cc259394c6",
}
REPAIR_V2_2_REJECTED_SAMPLE_IDS = {
    "siev1_5fcd8b26cb8ec0b1",
    "siev1_4904f5ddf778d528",
    "siev1_c08a5ea6290e63b2",
    "siev1_f6d3732cd3b46d43",
}
MANIFEST_FIELDS = (
    "old_sample_id",
    "new_sample_id",
    "label",
    "expected_action",
    "replacement_reason",
    "generation_version",
)
EXPECTED_REPLACEMENTS = {
    ("ad", "sanitize"): 9,
    ("porn", "sanitize"): 10,
    ("violence", "sanitize"): 10,
    ("sensitive", "sanitize"): 10,
    ("porn", "block"): 1,
}
ORIGINAL_BASELINE_PATHS = (
    "data/evaluation/semantic_independent_eval_v1_candidates.csv",
    "reports/manual_review/semantic_independent_eval_v1_review_template.csv",
    "reports/manual_review/semantic_independent_eval_v1_trial30.csv",
    "reports/manual_review/semantic_independent_eval_v1_sanitize_audit.csv",
    "reports/manual_review/semantic_independent_eval_v1_review_rules_v1.md",
    "reports/manual_review/semantic_independent_eval_v1_repair_trial13_v1.csv",
    "reports/manual_review/semantic_independent_eval_v1_repair_trial12_v2.csv",
    "reports/manual_review/semantic_independent_eval_v1_repair_trial8_v2_1.csv",
    "reports/manual_review/semantic_independent_eval_v1_repair_v2_1_sanitize_review.csv",
    "reports/manual_review/semantic_independent_eval_v1_repair_v2_1_review_ad.csv",
    "reports/manual_review/semantic_independent_eval_v1_repair_v2_1_review_porn.csv",
    "reports/manual_review/semantic_independent_eval_v1_repair_v2_1_review_violence.csv",
    "reports/manual_review/semantic_independent_eval_v1_repair_v2_1_review_sensitive.csv",
    "reports/manual_review/semantic_independent_eval_v1_repair_v2_linkage_audit.csv",
    "reports/data_audit_semantic_gold_v1_repaired/"
    "semantic_linkage_audit_v2_1.csv",
)


REPLACEMENT_SPECS = (
    # ad / sanitize: the promotional fragment is present and removable.
    (
        "ad",
        "sanitize",
        "medium",
        "direct_solicitation",
        "课程将在周四晚线上直播，回复“优惠”可获得私下购买入口。",
    ),
    (
        "ad",
        "sanitize",
        "medium",
        "symbol_obfuscation",
        "新版本修复了同步故障，加-微领取限时折扣码。",
    ),
    (
        "ad",
        "sanitize",
        "medium",
        "private_discount",
        "读书会本月讨论科幻作品，私信本账号可以拿内部会员价。",
    ),
    (
        "ad",
        "sanitize",
        "medium",
        "group_solicitation",
        "展览每天十点开放，扫码加入促销群还能领取赠品。",
    ),
    (
        "ad",
        "sanitize",
        "medium",
        "contact_solicitation",
        "菜单新增两款无糖饮品，联系个人号预订可享隐藏折扣。",
    ),
    (
        "ad",
        "sanitize",
        "medium",
        "agent_recruitment",
        "摄影课程包含三次外拍，回复“代理”即可获得招募入口。",
    ),
    (
        "ad",
        "sanitize",
        "medium",
        "paid_activation",
        "软件支持离线阅读，私聊购买激活资格后可提前使用。",
    ),
    (
        "ad",
        "sanitize",
        "medium",
        "group_solicitation",
        "社区团购周五配送，加群转账可以得到未公开优惠。",
    ),
    (
        "ad",
        "sanitize",
        "medium",
        "spaced_obfuscation",
        "演出座位图已经公布，私 xing 我可拿低价票。",
    ),
    # porn / sanitize: an explicit or promotional span is present inside useful content.
    (
        "porn",
        "sanitize",
        "medium",
        "explicit_quote",
        "这部影片前半段节奏舒缓，角色却说“今晚来我房间脱光”，结尾回到家庭和解。",
    ),
    (
        "porn",
        "sanitize",
        "medium",
        "sensational_title",
        "小说主要讨论婚姻沟通，章节标题却写成“深夜裸聊实录”。",
    ),
    (
        "porn",
        "sanitize",
        "medium",
        "explicit_promotion",
        "摄影展关注身体自主，海报角落印着“无码私密照合集”。",
    ),
    (
        "porn",
        "sanitize",
        "medium",
        "clickbait_title",
        "健康课程介绍青春期知识，宣传标题用了“成人视频教学”。",
    ),
    (
        "porn",
        "sanitize",
        "medium",
        "explicit_quote",
        "影评肯定演员表演，同时逐字引用“脱掉衣服给我看”的台词。",
    ),
    (
        "porn",
        "sanitize",
        "medium",
        "explicit_solicitation",
        "音乐节攻略列清了交通路线，末尾却加上“夜间裸聊房间招募”。",
    ),
    (
        "porn",
        "sanitize",
        "medium",
        "explicit_promotion",
        "旅行日记记录沿海风景，中间插入“付费观看露骨视频”的推广语。",
    ),
    (
        "porn",
        "sanitize",
        "medium",
        "explicit_promotion",
        "广播剧讲述成年人的情感选择，广告插曲却喊着“成人裸聊体验”。",
    ),
    (
        "porn",
        "sanitize",
        "medium",
        "clickbait_title",
        "服装测评介绍面料和尺码，标题却使用“色情自拍专区”吸引点击。",
    ),
    (
        "porn",
        "sanitize",
        "medium",
        "mixed_obfuscation",
        "舞蹈节目介绍编排理念，屏幕字幕突然出现“约pao直播入口”。",
    ),
    # violence / sanitize: a bounded low-to-medium threat can be removed.
    (
        "violence",
        "sanitize",
        "medium",
        "conditional_threat",
        "会议可以改到明天下午，你再迟到我就揍你一顿。",
    ),
    (
        "violence",
        "sanitize",
        "medium",
        "conditional_threat",
        "请在周五前归还借走的书，否则见面就给你一拳。",
    ),
    (
        "violence",
        "sanitize",
        "medium",
        "mild_threat",
        "球队训练改到室内，谁再失误我就踹谁。",
    ),
    (
        "violence",
        "sanitize",
        "medium",
        "conditional_threat",
        "活动预算还可以继续讨论，不同意我的方案我就动手打人。",
    ),
    (
        "violence",
        "sanitize",
        "medium",
        "conditional_threat",
        "我已经收到你的道歉，再提这件事我就扇你一巴掌。",
    ),
    (
        "violence",
        "sanitize",
        "medium",
        "physical_intimidation",
        "排队时请遵守先来后到，插队的人我会把他推倒。",
    ),
    (
        "violence",
        "sanitize",
        "medium",
        "conditional_threat",
        "邻里噪声可以请物业协调，再吵我就砸门教训你。",
    ),
    (
        "violence",
        "sanitize",
        "medium",
        "mild_threat",
        "项目分工今晚确认，谁再嘲笑我我就推他一把。",
    ),
    (
        "violence",
        "sanitize",
        "medium",
        "property_threat",
        "停车位编号是B12，再占用我就砸你的车。",
    ),
    (
        "violence",
        "sanitize",
        "medium",
        "conditional_threat",
        "演出结束后大家从东门离场，敢起哄我就动手教训他。",
    ),
    # sensitive / sanitize: synthetic privacy or health spans are explicitly present.
    (
        "sensitive",
        "sanitize",
        "medium",
        "health_privacy",
        "班级活动周五出发，名单备注“李同学正在接受抑郁症治疗”。",
    ),
    (
        "sensitive",
        "sanitize",
        "medium",
        "location_privacy",
        "投诉正文说明电梯连续故障，末尾留下住户地址“示例花园7栋302室”。",
    ),
    (
        "sensitive",
        "sanitize",
        "medium",
        "medical_identifier",
        "公益访谈介绍康复经验，署名旁保留病历编号“DEMO-MH-204”。",
    ),
    (
        "sensitive",
        "sanitize",
        "medium",
        "health_privacy",
        "会议纪要记录设备采购，备注写着“王同学曾接受精神科治疗”。",
    ),
    (
        "sensitive",
        "sanitize",
        "medium",
        "location_privacy",
        "社区通知公布今晚停水，同时列出独居住户门牌“8栋201室”。",
    ),
    (
        "sensitive",
        "sanitize",
        "medium",
        "health_privacy",
        "活动复盘感谢所有参与者，附件把匿名受访者写成“陈某，HIV阳性”。",
    ),
    (
        "sensitive",
        "sanitize",
        "medium",
        "contact_privacy",
        "快递投诉说明包裹外壳破损，正文附上收件邮箱“test-user@example.invalid”。",
    ),
    (
        "sensitive",
        "sanitize",
        "medium",
        "combined_privacy",
        "住宿申请说明需要安静房型，备注公开“同性伴侣同住，正在接受焦虑治疗”。",
    ),
    (
        "sensitive",
        "sanitize",
        "medium",
        "medical_identifier",
        "我愿意继续接受心理咨询，请不要联系单位；病历编号是DEMO-317。",
    ),
    (
        "sensitive",
        "sanitize",
        "medium",
        "self_harm_support",
        "求助者说自己有伤害自己的念头，并留下地址“示例街12号”请求上门支持。",
    ),
    # porn / block: the principal harm is explicit-content distribution.
    (
        "porn",
        "block",
        "high",
        "explicit_distribution",
        "建立付费群批量传播露骨成人视频，并要求成员付费解锁下载目录。",
    ),
)

STRUCTURE_METADATA_FIELDS = (
    "sample_id",
    "text",
    "label",
    "structure_type",
    "risk_position",
    "sanitize_operation",
    "risk_fragment",
    "sanitized_text",
    "template_signature",
    "semantic_relation",
    "obvious_two_part",
    "safe_context_reference",
    "severe_core_intent",
    "uses_real_identifier",
)


def _sanitize_spec(
    label: str,
    scenario: str,
    text: str,
    structure_type: str,
    risk_position: str,
    sanitize_operation: str,
    risk_fragment: str,
    sanitized_text: str,
    template_signature: str,
    semantic_relation: str,
    *,
    obvious_two_part: bool = False,
    source_version: str = "repair_v2_1",
) -> dict[str, Any]:
    return {
        "label": label,
        "expected_action": "sanitize",
        "risk_level": "medium",
        "scenario": scenario,
        "text": text,
        "structure_type": structure_type,
        "risk_position": risk_position,
        "sanitize_operation": sanitize_operation,
        "risk_fragment": risk_fragment,
        "sanitized_text": sanitized_text,
        "template_signature": template_signature,
        "semantic_relation": semantic_relation,
        "obvious_two_part": obvious_two_part,
        "safe_context_reference": False,
        "severe_core_intent": False,
        "uses_real_identifier": False,
        "source_version": source_version,
    }


REPAIR_V2_1_SANITIZE_SPECS = (
    _sanitize_spec(
        "ad", "refund_solicitation",
        "加虚构客服号 WX-DEMO-INVALID 领取返现；保修登记仍按订单编号办理。",
        "opening_fragment", "opening", "remove_private_channel",
        "加虚构客服号 WX-DEMO-INVALID 领取返现", "保修登记仍按订单编号办理。",
        "ad_opening_semicolon_service_notice", "返现私域引流污染保修通知",
        obvious_two_part=True,
    ),
    _sanitize_spec(
        "ad", "title_promotion",
        "【私聊示例账号 AD-DEMO-000 可拿内部价】周末手作市集九点开场，现场可正常购票。",
        "title_pollution", "opening", "remove_polluted_title",
        "【私聊示例账号 AD-DEMO-000 可拿内部价】", "周末手作市集九点开场，现场可正常购票。",
        "ad_bracket_title_market_notice", "私聊内部价标题污染市集通知",
    ),
    _sanitize_spec(
        "ad", "private_group",
        "展览导览分上午和下午两场，扫码进入私域团购群可享隐藏价，预约仍以官网编号为准。",
        "embedded_clause", "middle", "remove_private_channel",
        "扫码进入私域团购群可享隐藏价", "展览导览分上午和下午两场，预约仍以官网编号为准。",
        "ad_mid_clause_exhibition_booking", "私域团购引流嵌入展览预约信息",
    ),
    _sanitize_spec(
        "ad", "printed_promotion",
        "咖啡店今日供应两款无糖饮品，杯套同时宣传私信暗号拿未公开折扣。",
        "same_sentence_embedded", "embedded", "neutralize_promotion",
        "私信暗号拿未公开折扣", "咖啡店今日供应两款无糖饮品，杯套采用普通新品说明。",
        "ad_cup_sleeve_embedded_discount", "折扣暗号与饮品杯套宣传自然相关",
    ),
    _sanitize_spec(
        "ad", "form_pollution",
        "活动报名表：主题=城市摄影；地点=文化馆；推广备注=联系虚构代理号 AGENT-INVALID 购买加急名额；费用=公开价。",
        "field_pollution", "middle", "remove_polluted_field",
        "推广备注=联系虚构代理号 AGENT-INVALID 购买加急名额；", "活动报名表：主题=城市摄影；地点=文化馆；费用=公开价。",
        "ad_form_field_agent_slot", "代理招揽污染活动报名字段",
    ),
    _sanitize_spec(
        "ad", "signature_promotion",
        "软件更新说明：新增离线阅读并修复同步问题。签名：加入示例促销群 GROUP-000 获取付费激活码。",
        "signature_pollution", "end", "remove_private_channel",
        "签名：加入示例促销群 GROUP-000 获取付费激活码。", "软件更新说明：新增离线阅读并修复同步问题。",
        "ad_signature_group_activation", "促销群签名污染软件更新说明",
        obvious_two_part=True,
    ),
    _sanitize_spec(
        "ad", "service_dialogue",
        "顾客：周末蛋糕还能预订吗？店员：可以，私聊个人号还能拿隐藏返利，取货时间仍是下午三点。",
        "dialogue", "middle", "replace_with_official_channel",
        "私聊个人号还能拿隐藏返利", "顾客：周末蛋糕还能预订吗？店员：可以，请通过门店公开渠道预订，取货时间仍是下午三点。",
        "ad_dialogue_cake_hidden_rebate", "隐藏返利与蛋糕预订服务自然相关",
    ),
    _sanitize_spec(
        "ad", "list_pollution",
        "课程安排｜基础构图｜户外练习｜私下转账到 PAY-INVALID 可提前解锁资料｜结课讲评",
        "list_pollution", "embedded", "remove_private_channel",
        "私下转账到 PAY-INVALID 可提前解锁资料｜", "课程安排｜基础构图｜户外练习｜结课讲评",
        "ad_pipe_list_private_payment", "私下付费渠道污染课程安排列表",
    ),
    _sanitize_spec(
        "ad", "charity_private_sale",
        "社区义卖所得将用于公共阅读角，现场也接受正常购买；想拿专享价就进私域群预付。",
        "closing_fragment", "end", "delete_promotion_clause",
        "想拿专享价就进私域群预付", "社区义卖所得将用于公共阅读角，现场也接受正常购买。",
        "ad_closing_private_presale", "私域预付招揽附着于义卖信息",
        obvious_two_part=True,
    ),
    _sanitize_spec(
        "porn", "performance_page_popup",
        "社区演出报名页顶部弹出“成人裸聊体验 PORN-DEMO-INVALID”，节目时间和无障碍入场说明仍在下方。",
        "opening_fragment", "opening", "remove_solicitation",
        "顶部弹出“成人裸聊体验 PORN-DEMO-INVALID”，", "社区演出报名页的节目时间和无障碍入场说明仍在下方。",
        "porn_opening_performance_popup", "色情弹窗来自同一演出报名页的广告位污染",
        obvious_two_part=True,
    ),
    _sanitize_spec(
        "porn", "title_solicitation",
        "【付费裸聊体验招募】周末市集摊位图、无障碍通道和公交路线如下。",
        "title_pollution", "opening", "remove_polluted_title",
        "【付费裸聊体验招募】", "周末市集摊位图、无障碍通道和公交路线如下。",
        "porn_bracket_title_market_map", "裸聊招募标题污染市集信息",
    ),
    _sanitize_spec(
        "porn", "travel_page_promotion",
        "旅行页面先列出沿海步道，随后宣传付费观看露骨视频，再提供公共交通时刻。",
        "embedded_clause", "middle", "delete_explicit_promotion",
        "随后宣传付费观看露骨视频，", "旅行页面先列出沿海步道，再提供公共交通时刻。",
        "porn_mid_travel_promotion_transit", "色情推广插入旅行页面内容",
    ),
    _sanitize_spec(
        "porn", "ui_button_pollution",
        "健身应用的课程卡片把“无码私密照合集”设为跳转按钮，其他训练计划仍可正常使用。",
        "ui_pollution", "embedded", "replace_with_neutral_placeholder",
        "“无码私密照合集”", "健身应用的课程卡片使用“查看课程详情”按钮，其他训练计划仍可正常使用。",
        "porn_ui_button_fitness_card", "色情按钮污染健身应用界面",
    ),
    _sanitize_spec(
        "porn", "page_field_pollution",
        "民宿页面字段：入住=15:00；退房=11:00；弹窗=夜间裸聊房招募；早餐=一层餐厅。",
        "field_pollution", "middle", "remove_polluted_field",
        "弹窗=夜间裸聊房招募；", "民宿页面字段：入住=15:00；退房=11:00；早餐=一层餐厅。",
        "porn_field_popup_guesthouse", "裸聊招募弹窗污染民宿页面字段",
    ),
    _sanitize_spec(
        "porn", "podcast_ad_pollution",
        "播客信息｜主题：成年人的沟通｜中场广告：付费解锁露骨自拍视频｜时长：35分钟",
        "list_pollution", "middle", "delete_explicit_promotion",
        "中场广告：付费解锁露骨自拍视频｜", "播客信息｜主题：成年人的沟通｜时长：35分钟",
        "porn_pipe_podcast_midroll", "色情付费广告污染播客信息",
    ),
    _sanitize_spec(
        "porn", "host_solicitation",
        "听众问海岛路线怎么走，主播回答公交换乘后又说：“进入示例房间 PORN-VOID 参加裸聊体验。”",
        "dialogue", "end", "remove_solicitation",
        "又说：“进入示例房间 PORN-VOID 参加裸聊体验。”", "听众问海岛路线怎么走，主播回答了公交换乘方式。",
        "porn_dialogue_island_room_invite", "裸聊招揽发生在路线问答场景中",
    ),
    _sanitize_spec(
        "porn", "support_chat_promotion",
        "顾客询问外套尺码，客服答复库存后追加“付费解锁露骨自拍包”，并继续说明退换期限。",
        "dialogue", "embedded", "delete_explicit_promotion",
        "追加“付费解锁露骨自拍包”，", "顾客询问外套尺码，客服答复库存并说明退换期限。",
        "porn_dialogue_clothing_upsell", "色情付费推销污染正常客服对话",
    ),
    _sanitize_spec(
        "porn", "creator_signature_promotion",
        "摄影社区的作品说明记录了海边日落参数。发布者签名：示例房间 PORN-SIGN-INVALID 提供付费裸聊。",
        "signature_pollution", "end", "remove_polluted_signature",
        "发布者签名：示例房间 PORN-SIGN-INVALID 提供付费裸聊。", "摄影社区的作品说明记录了海边日落参数。",
        "porn_signature_creator_profile", "色情推广签名来自同一摄影社区发布者资料",
        obvious_two_part=True,
    ),
    _sanitize_spec(
        "porn", "navigation_button_pollution",
        "摄影作品页展示海边日落，却用“色情直播体验”按钮替代正常的下一页链接。",
        "ui_pollution", "embedded", "replace_with_neutral_placeholder",
        "“色情直播体验”", "摄影作品页展示海边日落，并使用“下一页”按钮继续浏览。",
        "porn_ui_photo_navigation", "色情直播按钮污染摄影作品导航",
    ),
    _sanitize_spec(
        "violence", "opening_mild_threat",
        "再打断我就推你一下；小组讨论仍按发言顺序进行。",
        "opening_fragment", "opening", "rewrite_nonviolent",
        "再打断我就推你一下", "如有不同意见请依次发言；小组讨论仍按发言顺序进行。",
        "violence_opening_push_discussion", "轻度威胁发生于小组发言冲突",
        obvious_two_part=True,
    ),
    _sanitize_spec(
        "violence", "title_intimidation",
        "【谁反对就推谁】社团预算讨论纪要：场地费与材料费下周再核对。",
        "title_pollution", "opening", "remove_polluted_title",
        "【谁反对就推谁】", "社团预算讨论纪要：场地费与材料费下周再核对。",
        "violence_bracket_title_budget_minutes", "威胁性标题污染预算纪要",
    ),
    _sanitize_spec(
        "violence", "meeting_threat",
        "会议改到三点，你再迟到我就扇你一下，然后我们继续确认分工。",
        "same_sentence_embedded", "middle", "rewrite_nonviolent",
        "你再迟到我就扇你一下", "会议改到三点，请按时参加，然后我们继续确认分工。",
        "violence_mid_meeting_lateness", "迟到威胁与会议时间自然相关",
    ),
    _sanitize_spec(
        "violence", "team_page_conflict",
        "组员：演示顺序需要调整吗？负责人：可以，但你再擅自改我的页面我就推你。组员：那我们按版本记录确认后再改。",
        "dialogue", "middle", "rewrite_nonviolent",
        "但你再擅自改我的页面我就推你",
        "组员：演示顺序需要调整吗？负责人：可以，但修改前请先和我确认。组员：那我们按版本记录确认后再改。",
        "violence_dialogue_team_page_conflict", "轻度推人威胁与团队协作中的页面修改冲突自然相关",
        source_version="repair_v2_2",
    ),
    _sanitize_spec(
        "violence", "queue_record",
        "值班记录：区域=A区；秩序备注=再插队就把他推开；交接=18:00。",
        "field_pollution", "middle", "remove_threat_field",
        "秩序备注=再插队就把他推开；", "值班记录：区域=A区；交接=18:00。",
        "violence_field_queue_record", "推搡威胁污染值班秩序字段",
    ),
    _sanitize_spec(
        "violence", "training_signature",
        "训练安排｜热身十分钟｜传球练习｜队长签名：再失误就踹你｜拉伸放松",
        "list_pollution", "embedded", "remove_threat_field",
        "队长签名：再失误就踹你｜", "训练安排｜热身十分钟｜传球练习｜拉伸放松",
        "violence_pipe_training_signature", "踢人威胁污染球队训练安排",
    ),
    _sanitize_spec(
        "violence", "neighbor_dialogue",
        "甲：音量能调低吗？乙：可以，但你再敲门我就推你。甲：那我们十点后保持安静。",
        "dialogue", "middle", "rewrite_nonviolent",
        "但你再敲门我就推你", "甲：音量能调低吗？乙：可以，请直接沟通。甲：那我们十点后保持安静。",
        "violence_dialogue_neighbor_noise", "推人威胁发生在邻里噪声协商中",
    ),
    _sanitize_spec(
        "violence", "workplace_dialogue",
        "同事：方案还要修改吗？负责人：可以讨论，谁再嘲笑我我就打谁。",
        "dialogue", "end", "rewrite_nonviolent",
        "谁再嘲笑我我就打谁", "同事：方案还要修改吗？负责人：可以讨论，请保持尊重。",
        "violence_dialogue_workplace_mockery", "打人威胁发生在工作讨论冲突中",
    ),
    _sanitize_spec(
        "violence", "parking_signature",
        "停车区本周重新划线，临时车位从西门进入。留言：再占我的位置就踢你。",
        "signature_pollution", "end", "remove_polluted_signature",
        "留言：再占我的位置就踢你。", "停车区本周重新划线，临时车位从西门进入。",
        "violence_signature_parking_notice", "踢人威胁污染停车通知留言",
        obvious_two_part=True,
    ),
    _sanitize_spec(
        "violence", "indoor_match_threat",
        "比赛改在室内，输球我就给你一巴掌，训练时间仍是周六上午。",
        "same_sentence_embedded", "middle", "rewrite_nonviolent",
        "输球我就给你一巴掌", "比赛改在室内，请认真配合，训练时间仍是周六上午。",
        "violence_mid_match_schedule", "轻度威胁与球队比赛结果自然相关",
    ),
    _sanitize_spec(
        "sensitive", "opening_health_identifier",
        "测试用户甲（虚构）的心理治疗记录号 DEMO-MH-000 出现在预约单顶部；预约时间仍为周二下午。",
        "opening_fragment", "opening", "redact_identifier",
        "测试用户甲（虚构）的心理治疗记录号 DEMO-MH-000 出现在预约单顶部；", "预约时间仍为周二下午。",
        "sensitive_opening_record_appointment", "虚构心理治疗编号污染预约单",
    ),
    _sanitize_spec(
        "sensitive", "appointment_title_health_privacy",
        "心理咨询预约确认单标题：测试用户A（虚构），焦虑症治疗中；正文仅列出周三预约时段和取消规则。",
        "title_pollution", "opening", "remove_polluted_title",
        "标题：测试用户A（虚构），焦虑症治疗中；", "心理咨询预约确认单正文仅列出周三预约时段和取消规则。",
        "sensitive_title_appointment_health", "健康隐私标题来自同一心理咨询预约确认单",
    ),
    _sanitize_spec(
        "sensitive", "care_lodging_health",
        "住宿照护申请确认周五入住，公开摘要却写明“测试成员丙（虚构）正在接受抑郁治疗，夜间药物由同行照护员提醒”，房型仍为安静单间。",
        "same_sentence_embedded", "middle", "redact_health_support",
        "公开摘要却写明“测试成员丙（虚构）正在接受抑郁治疗，夜间药物由同行照护员提醒”",
        "住宿照护申请确认周五入住，健康支持详情已转入保密照护记录，房型仍为安静单间。",
        "sensitive_field_care_lodging_health", "治疗与用药信息源自同一住宿照护流程，但不应出现在公开摘要",
        source_version="repair_v2_2",
    ),
    _sanitize_spec(
        "sensitive", "lodging_public_note",
        "住宿申请：房型=安静单间；公开备注=同性伴侣同住、正在接受焦虑治疗；入住=周五。",
        "field_pollution", "middle", "remove_health_note",
        "公开备注=同性伴侣同住、正在接受焦虑治疗；", "住宿申请：房型=安静单间；入住=周五。",
        "sensitive_field_lodging_note", "关系与健康隐私污染住宿申请公开备注",
    ),
    _sanitize_spec(
        "sensitive", "delivery_contact_field",
        "快递改派单：原因=包装破损；收件邮箱=demo-user@example.invalid；新时段=周六上午。",
        "field_pollution", "middle", "redact_identifier",
        "收件邮箱=demo-user@example.invalid；", "快递改派单：原因=包装破损；收件邮箱=[已遮盖]；新时段=周六上午。",
        "sensitive_field_delivery_email", "虚构联系字段与快递改派单自然相关",
    ),
    _sanitize_spec(
        "sensitive", "maintenance_location_field",
        "社区上门检修名单｜楼栋=示例楼｜独居住户门牌=DEMO-ROOM-000｜时段=14:00",
        "list_pollution", "embedded", "generalize_private_field",
        "独居住户门牌=DEMO-ROOM-000｜", "社区上门检修名单｜楼栋=示例楼｜住户门牌=[已遮盖]｜时段=14:00",
        "sensitive_pipe_maintenance_room", "虚构门牌与上门检修名单自然相关",
    ),
    _sanitize_spec(
        "sensitive", "school_health_safeguard",
        "校医：校内运动日保障表准备好了吗？班主任：公开栏误写了“测试学生乙（虚构）正在接受抑郁治疗，午间用药由校医保管”。校医：请转入保密健康档案，集合仍在医务室旁。",
        "dialogue", "embedded", "redact_health_support",
        "公开栏误写了“测试学生乙（虚构）正在接受抑郁治疗，午间用药由校医保管”",
        "校医：校内运动日保障表准备好了吗？班主任：健康保障详情已转入保密健康档案。校医：集合仍在医务室旁。",
        "sensitive_field_school_health_safeguard", "治疗与用药信息直接服务校内活动保障，但公开栏造成不当泄露",
        source_version="repair_v2_2",
    ),
    _sanitize_spec(
        "sensitive", "support_location_dialogue",
        "值班员：可以安排上门支持。求助者：我的演示门牌是 DEMO-STREET-000，请不要在群里公开。",
        "dialogue", "end", "redact_identifier",
        "我的演示门牌是 DEMO-STREET-000，", "值班员：可以安排上门支持。求助者：请通过私密渠道确认位置，不要在群里公开。",
        "sensitive_dialogue_support_location", "虚构位置字段与上门支持场景自然相关",
    ),
    _sanitize_spec(
        "sensitive", "health_support_registration",
        "健康互助登记表：支持主题=长期用药提醒；公开备注误写=测试成员甲（虚构），HIV治疗随访中；服务安排=每周一次私密回访。",
        "field_pollution", "middle", "redact_health_support",
        "公开备注误写=测试成员甲（虚构），HIV治疗随访中；",
        "健康互助登记表：支持主题=长期用药提醒；健康信息=[转入保密登记]；服务安排=每周一次私密回访。",
        "sensitive_field_health_support_registration", "治疗随访信息与健康支持登记直接相关，但公开备注造成不当泄露",
        source_version="repair_v2_2",
    ),
    _sanitize_spec(
        "sensitive", "appointment_summary_identifier",
        "康复预约确认单把病历编号 DEMO-PSY-317 和下次咨询时间写在同一公开摘要中。",
        "same_sentence_embedded", "embedded", "redact_identifier",
        "病历编号 DEMO-PSY-317 和", "康复预约确认单只在公开摘要中保留下次咨询时间。",
        "sensitive_mid_appointment_summary", "虚构病历编号与康复预约确认单自然相关",
    ),
)

REPAIR_V1_SANITIZE_REFERENCES = tuple(
    {"label": label, "text": text}
    for label, action, _risk, _scenario, text in REPLACEMENT_SPECS
    if action == "sanitize"
)


def _porn_block_v1_spec() -> dict[str, str]:
    label, action, risk_level, scenario, text = REPLACEMENT_SPECS[-1]
    if (label, action) != ("porn", "block"):
        raise ValueError("Repair V1 porn/block specification is missing")
    return {
        "label": label,
        "expected_action": action,
        "risk_level": risk_level,
        "scenario": scenario,
        "text": text,
    }

def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sample_text_hash(rows: list[dict[str, str]], sample_ids: set[str]) -> str:
    import hashlib

    selected = {
        row["sample_id"]: row["text"]
        for row in rows
        if row["sample_id"] in sample_ids
    }
    if set(selected) != sample_ids:
        missing = sorted(sample_ids - set(selected))
        raise ValueError(f"protected sanitize candidates missing: {missing}")
    payload = "\n".join(
        f"{sample_id}\t{selected[sample_id]}" for sample_id in sorted(selected)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _path_label(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _replacement_reason(old_row: dict[str, str]) -> str:
    if old_row["sample_id"] == PORN_BLOCK_REJECTED_ID:
        return "原porn/block样本的主要危害是私密影像勒索与隐私侵害，主标签不准确"
    repair_v2_2_reasons = {
        "siev1_90ae570c37556d87": (
            "Repair V2.2人工rejected定向修复：借书逾期提醒中的推人威胁"
            "缺少自然施威者与业务关联"
        ),
        "siev1_6a93f9318c963bf2": (
            "Repair V2.2人工rejected定向修复：普通互助活动签到备注中的"
            "HIV状态与业务流程关联不足"
        ),
        "siev1_4669068bc0a6f025": (
            "Repair V2.2人工rejected定向修复：普通学校春游名单中的"
            "抑郁治疗信息缺少照护、用药或安全保障关系"
        ),
        "siev1_429441cc259394c6": (
            "Repair V2.2人工rejected定向修复：普通社团出行名单中的"
            "抑郁治疗信息与行程安排关联不足"
        ),
    }
    if old_row["sample_id"] in repair_v2_2_reasons:
        return repair_v2_2_reasons[old_row["sample_id"]]
    if old_row["sample_id"] in REPAIR_V2_1_REPLACED_OLD_IDS:
        return "Repair V2.1语义关联专项修复：替换V2中合法主体与风险片段无自然业务关联的候选"
    return "Repair V2.1语义关联专项复核：保留V2中已确认具有自然业务关联的sanitize候选"

def _all_replacement_specs() -> tuple[dict[str, Any], ...]:
    return (*REPAIR_V2_1_SANITIZE_SPECS, _porn_block_v1_spec())


def build_replacement_rows() -> list[dict[str, str]]:
    counters: Counter[tuple[str, str]] = Counter()
    rows: list[dict[str, str]] = []
    for spec in _all_replacement_specs():
        label = str(spec["label"])
        action = str(spec["expected_action"])
        counters[(label, action)] += 1
        index = counters[(label, action)]
        is_preserved_block = (label, action) == ("porn", "block")
        source_version = (
            "repaired" if is_preserved_block else str(spec["source_version"])
        )
        rows.append(
            {
                "sample_id": stable_sample_id(str(spec["text"]), label),
                "text": str(spec["text"]),
                "label": label,
                "risk_level": str(spec["risk_level"]),
                "expected_action": action,
                "scenario": str(spec["scenario"]),
                "source_type": "independent_synthetic_replacement_candidate",
                "source_reference": (
                    f"curated_independent_v1_{source_version}:"
                    f"{label}:{action}:{index:02d}"
                ),
                "review_status": "pending",
                "reviewer": "",
                "notes": "repaired candidate; independent human review required",
            }
        )
    if dict(counters) != EXPECTED_REPLACEMENTS:
        raise ValueError(f"invalid replacement specification distribution: {dict(counters)}")
    ids = [row["sample_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("replacement specifications produce duplicate sample_id values")
    v1_ids = {
        stable_sample_id(row["text"], row["label"])
        for row in REPAIR_V1_SANITIZE_REFERENCES
    }
    v2_sanitize_ids = {
        row["sample_id"] for row in rows if row["expected_action"] == "sanitize"
    }
    if v1_ids & v2_sanitize_ids:
        raise ValueError("Repair V2.1 sanitize sample_id overlaps Repair V1")
    if REPAIR_V2_UNLINKED_SAMPLE_IDS & v2_sanitize_ids:
        raise ValueError("Repair V2.1 still contains a V2 unlinked sample_id")
    return rows


def build_structure_metadata() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for spec in REPAIR_V2_1_SANITIZE_SPECS:
        rows.append(
            {
                "sample_id": stable_sample_id(str(spec["text"]), str(spec["label"])),
                "text": str(spec["text"]),
                "label": str(spec["label"]),
                "structure_type": str(spec["structure_type"]),
                "risk_position": str(spec["risk_position"]),
                "sanitize_operation": str(spec["sanitize_operation"]),
                "risk_fragment": str(spec["risk_fragment"]),
                "sanitized_text": str(spec["sanitized_text"]),
                "template_signature": str(spec["template_signature"]),
                "semantic_relation": str(spec["semantic_relation"]),
                "obvious_two_part": str(bool(spec["obvious_two_part"])).lower(),
                "safe_context_reference": str(bool(spec["safe_context_reference"])).lower(),
                "severe_core_intent": str(bool(spec["severe_core_intent"])).lower(),
                "uses_real_identifier": str(bool(spec["uses_real_identifier"])).lower(),
            }
        )
    return rows


def build_semantic_linkage_audit() -> list[dict[str, str]]:
    mechanisms = {
        "opening_fragment": "风险开场由同一业务页面或通知中的广告位、用户输入或错误字段产生",
        "title_pollution": "风险标题位于同一页面、记录或活动条目的标题区",
        "embedded_clause": "风险短句嵌入同一页面的连续业务内容",
        "same_sentence_embedded": "风险片段嵌入同一业务句内部",
        "field_pollution": "风险字段属于同一表单、页面或记录",
        "signature_pollution": "风险内容来自同一发布者、记录参与者的签名或留言区",
        "dialogue": "风险表达由同一自然对话中的参与者产生",
        "list_pollution": "风险项混入同一业务列表",
        "closing_fragment": "风险尾句延续同一活动或交易主题",
        "ui_pollution": "风险按钮出现在同一应用或页面界面",
        "quote_pollution": "风险措辞是同一业务提醒实际使用的文本",
    }
    rows: list[dict[str, str]] = []
    for spec in REPAIR_V2_1_SANITIZE_SPECS:
        structure_type = str(spec["structure_type"])
        mechanism = mechanisms.get(
            structure_type,
            "风险片段来自同一业务内容中的局部污染",
        )
        rows.append(
            {
                "sample_id": stable_sample_id(str(spec["text"]), str(spec["label"])),
                "label": str(spec["label"]),
                "text": str(spec["text"]),
                "structure_type": structure_type,
                "risk_position": str(spec["risk_position"]),
                "sanitize_operation": str(spec["sanitize_operation"]),
                "legal_context": str(spec["sanitized_text"]),
                "risk_fragment": str(spec["risk_fragment"]),
                "linkage_reason": (
                    f"{spec['semantic_relation']}；{mechanism}，"
                    "风险片段与合法主体可在同一真实业务场景中自然共存。"
                ),
                "linkage_status": "linked",
                "notes": "Repair V2.1语义关联专项复核：linked",
            }
        )
    return rows

def build_repair_v1_references() -> list[dict[str, str]]:
    return [
        {
            "sample_id": stable_sample_id(row["text"], row["label"]),
            "text": row["text"],
            "label": row["label"],
        }
        for row in REPAIR_V1_SANITIZE_REFERENCES
    ]


def _load_eliminated_rows(
    original_rows: list[dict[str, str]],
    sanitize_audit_path: Path,
    trial_path: Path,
) -> list[dict[str, str]]:
    sanitize_rows = read_csv(sanitize_audit_path, CANDIDATE_FIELDS)
    if len(sanitize_rows) != 40:
        raise ValueError(f"sanitize audit must contain 40 rows, found {len(sanitize_rows)}")
    status_counts = Counter(row["review_status"] for row in sanitize_rows)
    if status_counts != {"verified": 1, "rejected": 39}:
        raise ValueError(f"unexpected sanitize audit status counts: {dict(status_counts)}")
    if any(row["expected_action"] != "sanitize" for row in sanitize_rows):
        raise ValueError("sanitize audit contains a non-sanitize row")
    rejected_ids = {
        row["sample_id"] for row in sanitize_rows if row["review_status"] == "rejected"
    }

    trial_rows = read_csv(trial_path, CANDIDATE_FIELDS)
    porn_block_review = [
        row for row in trial_rows if row["sample_id"] == PORN_BLOCK_REJECTED_ID
    ]
    if len(porn_block_review) != 1:
        raise ValueError("required rejected porn/block sample is missing from trial review")
    if porn_block_review[0]["review_status"] != "rejected":
        raise ValueError("required porn/block sample has not been rejected")

    eliminated_ids = rejected_ids | {PORN_BLOCK_REJECTED_ID}
    if len(eliminated_ids) != 40:
        raise ValueError(f"expected 40 eliminated ids, found {len(eliminated_ids)}")
    original_by_id = {row["sample_id"]: row for row in original_rows}
    missing = sorted(eliminated_ids - set(original_by_id))
    if missing:
        raise ValueError(f"eliminated sample ids missing from original candidates: {missing}")
    eliminated_rows = [
        dict(row) for row in original_rows if row["sample_id"] in eliminated_ids
    ]
    distribution = Counter(
        (row["label"], row["expected_action"]) for row in eliminated_rows
    )
    if dict(distribution) != EXPECTED_REPLACEMENTS:
        raise ValueError(f"invalid eliminated distribution: {dict(distribution)}")
    return eliminated_rows


def build_repaired_candidates(
    original_rows: list[dict[str, str]],
    eliminated_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    replacement_rows = build_replacement_rows()
    eliminated_by_stratum: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    replacement_by_stratum: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in eliminated_rows:
        eliminated_by_stratum[(row["label"], row["expected_action"])].append(row)
    for row in replacement_rows:
        replacement_by_stratum[(row["label"], row["expected_action"])].append(row)

    mapping: dict[str, dict[str, str]] = {}
    manifest_by_old_id: dict[str, dict[str, str]] = {}
    for stratum in EXPECTED_REPLACEMENTS:
        old_rows = eliminated_by_stratum[stratum]
        new_rows = replacement_by_stratum[stratum]
        if len(old_rows) != len(new_rows):
            raise ValueError(f"replacement count mismatch for {stratum}")
        for old_row, new_row in zip(old_rows, new_rows, strict=True):
            mapping[old_row["sample_id"]] = new_row
            manifest_by_old_id[old_row["sample_id"]] = {
                "old_sample_id": old_row["sample_id"],
                "new_sample_id": new_row["sample_id"],
                "label": old_row["label"],
                "expected_action": old_row["expected_action"],
                "replacement_reason": _replacement_reason(old_row),
                "generation_version": (
                    PORN_BLOCK_GENERATION_VERSION
                    if old_row["sample_id"] == PORN_BLOCK_REJECTED_ID
                    else (
                        GENERATION_VERSION
                        if old_row["sample_id"] in REPAIR_V2_2_REPLACED_OLD_IDS
                        else REPAIR_V2_1_GENERATION_VERSION
                    )
                ),
            }

    repaired_rows = [
        dict(mapping.get(row["sample_id"], row))
        for row in original_rows
    ]
    retained_ids = {
        row["sample_id"]
        for row in original_rows
        if row["sample_id"] not in mapping
    }
    new_ids = {row["sample_id"] for row in replacement_rows}
    if retained_ids & new_ids:
        raise ValueError("replacement sample_id collides with a retained candidate")
    validate_candidate_rows(repaired_rows)
    manifest = [
        manifest_by_old_id[row["sample_id"]]
        for row in original_rows
        if row["sample_id"] in manifest_by_old_id
    ]
    if len(manifest) != 40:
        raise ValueError(f"replacement manifest must contain 40 rows, found {len(manifest)}")
    return repaired_rows, replacement_rows, manifest


def run_repair(
    project_root: Path,
    original_path: Path,
    sanitize_audit_path: Path,
    trial_path: Path,
    output_path: Path,
    manifest_path: Path,
    review_template_path: Path,
    report_dir: Path,
    similarity_threshold: float = 0.55,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    protected_candidate_path = (
        project_root
        / "data/evaluation/semantic_independent_eval_v1_repaired_candidates.csv"
    )
    sanitize_review_path = (
        project_root
        / "reports/manual_review/"
        "semantic_independent_eval_v1_repair_v2_1_sanitize_review.csv"
    )
    historical_linkage_path = (
        project_root
        / "reports/data_audit_semantic_gold_v1_repaired/"
        "semantic_linkage_audit_v2_1.csv"
    )
    sanitize_review_rows = read_csv(sanitize_review_path, CANDIDATE_FIELDS)
    verified_ids = {
        row["sample_id"]
        for row in sanitize_review_rows
        if row["review_status"] == "verified"
    }
    rejected_ids = {
        row["sample_id"]
        for row in sanitize_review_rows
        if row["review_status"] == "rejected"
    }
    if len(verified_ids) != 35 or rejected_ids != REPAIR_V2_2_REJECTED_SAMPLE_IDS:
        raise ValueError(
            "Repair V2.2 requires the frozen 35 verified / 4 rejected sanitize review"
        )
    protected_before_hash = _sample_text_hash(
        read_csv(protected_candidate_path, CANDIDATE_FIELDS),
        verified_ids,
    )
    historical_linkage_rows = read_csv(
        historical_linkage_path,
        LINKAGE_AUDIT_FIELDS,
    )
    historical_repair_references = [
        {
            **row,
            "reference_id": f"repair_v2_1:{row['sample_id']}",
            "reference_file": historical_linkage_path.relative_to(project_root).as_posix(),
        }
        for row in historical_linkage_rows
    ]

    original_rows = read_csv(original_path, CANDIDATE_FIELDS)
    validate_candidate_rows(original_rows)
    eliminated_rows = _load_eliminated_rows(
        original_rows, sanitize_audit_path, trial_path
    )
    repaired_rows, replacement_rows, manifest = build_repaired_candidates(
        original_rows, eliminated_rows
    )
    structure_metadata = build_structure_metadata()
    semantic_linkage_rows = build_semantic_linkage_audit()
    repair_v1_references = build_repair_v1_references()

    original_hashes = {
        relative_path: _sha256_file(project_root / relative_path)
        for relative_path in ORIGINAL_BASELINE_PATHS
    }
    review_template_path.unlink(missing_ok=True)
    write_csv(output_path, CANDIDATE_FIELDS, repaired_rows)
    write_csv(manifest_path, MANIFEST_FIELDS, manifest)

    targeted_replacement_rows = [
        row
        for row in replacement_rows
        if "repair_v2_2" in row["source_reference"]
    ]
    if len(targeted_replacement_rows) != 4:
        raise ValueError(
            f"Repair V2.2 must generate exactly 4 targeted candidates, "
            f"found {len(targeted_replacement_rows)}"
        )
    targeted_coverage = audit_repaired_rows(
        project_root,
        targeted_replacement_rows,
        eliminated_rows,
        report_dir / "v2_2_targeted_candidates",
        candidate_file_label=(
            "data/evaluation/semantic_independent_eval_v1_replacement_manifest.csv"
            "#repair_v2_2_targeted_candidates"
        ),
        additional_reference_rows=[
            *repair_v1_references,
            *historical_repair_references,
        ],
        similarity_threshold=similarity_threshold,
    )
    new_coverage = audit_repaired_rows(
        project_root,
        replacement_rows,
        eliminated_rows,
        report_dir / "new_candidates",
        candidate_file_label=(
            "data/evaluation/semantic_independent_eval_v1_replacement_manifest.csv"
            "#new_candidates"
        ),
        additional_reference_rows=repair_v1_references,
        similarity_threshold=similarity_threshold,
    )
    repaired_coverage = audit_repaired_rows(
        project_root,
        repaired_rows,
        eliminated_rows,
        report_dir / "repaired_candidates",
        candidate_file_label=_path_label(output_path, project_root),
        additional_reference_rows=repair_v1_references,
        similarity_threshold=similarity_threshold,
    )
    structure_coverage = audit_structure_metadata(
        structure_metadata,
        report_dir,
        generation_version=GENERATION_VERSION,
    )
    linkage_coverage = audit_semantic_linkage(
        semantic_linkage_rows,
        {row["sample_id"] for row in structure_metadata},
        report_dir,
        generation_version=GENERATION_VERSION,
        forbidden_sample_ids=(
            REPAIR_V2_UNLINKED_SAMPLE_IDS | REPAIR_V2_2_REJECTED_SAMPLE_IDS
        ),
    )
    protected_after_hash = _sample_text_hash(repaired_rows, verified_ids)
    verified_samples_unchanged = protected_before_hash == protected_after_hash
    audit_passed = (
        targeted_coverage["hard_overlap_passed"]
        and new_coverage["hard_overlap_passed"]
        and repaired_coverage["hard_overlap_passed"]
        and structure_coverage["structure_audit_passed"]
        and linkage_coverage["semantic_linkage_audit_passed"]
        and verified_samples_unchanged
    )
    if audit_passed:
        write_csv(review_template_path, CANDIDATE_FIELDS, repaired_rows)

    current_original_hashes = {
        relative_path: _sha256_file(project_root / relative_path)
        for relative_path in ORIGINAL_BASELINE_PATHS
    }
    original_files_unchanged = original_hashes == current_original_hashes
    summary = {
        "schema_version": 2,
        "generation_version": GENERATION_VERSION,
        "replacement_count": len(manifest),
        "retained_count": len(repaired_rows) - len(manifest),
        "replacement_distribution": {
            f"{label}/{action}": count
            for (label, action), count in EXPECTED_REPLACEMENTS.items()
        },
        "v2_2_targeted_candidates_audit_passed": targeted_coverage[
            "hard_overlap_passed"
        ],
        "v2_2_targeted_candidates_audit": targeted_coverage,
        "new_candidates_audit_passed": new_coverage["hard_overlap_passed"],
        "repaired_candidates_audit_passed": repaired_coverage[
            "hard_overlap_passed"
        ],
        "structure_audit_passed": structure_coverage["structure_audit_passed"],
        "structure_audit": structure_coverage,
        "semantic_linkage_audit_passed": linkage_coverage[
            "semantic_linkage_audit_passed"
        ],
        "semantic_linkage_audit": linkage_coverage,
        "audit_passed": audit_passed,
        "review_template_generated": audit_passed,
        "original_files_unchanged": original_files_unchanged,
        "original_file_sha256": original_hashes,
        "verified_sanitize_candidate_count": len(verified_ids),
        "verified_sanitize_candidates_unchanged": verified_samples_unchanged,
        "verified_sanitize_sample_text_sha256_before": protected_before_hash,
        "verified_sanitize_sample_text_sha256_after": protected_after_hash,
        "output_sha256": {
            _path_label(output_path, project_root): _sha256_file(output_path),
            _path_label(manifest_path, project_root): _sha256_file(manifest_path),
            **(
                {
                    _path_label(review_template_path, project_root):
                    _sha256_file(review_template_path)
                }
                if audit_passed
                else {}
            ),
        },
    }
    write_json(report_dir / "summary.json", summary)
    if not original_files_unchanged:
        raise RuntimeError("original V1 files changed during repaired candidate generation")
    if not audit_passed:
        raise RuntimeError(
            "repaired candidate audit failed; review template was not generated"
        )
    return summary


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Build and audit repaired independent semantic evaluation V1 candidates."
    )
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument(
        "--original",
        type=Path,
        default=project_root
        / "data/evaluation/semantic_independent_eval_v1_candidates.csv",
    )
    parser.add_argument(
        "--sanitize-audit",
        type=Path,
        default=project_root
        / "reports/manual_review/semantic_independent_eval_v1_sanitize_audit.csv",
    )
    parser.add_argument(
        "--trial-review",
        type=Path,
        default=project_root
        / "reports/manual_review/semantic_independent_eval_v1_trial30.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root
        / "data/evaluation/semantic_independent_eval_v1_repaired_candidates.csv",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=project_root
        / "data/evaluation/semantic_independent_eval_v1_replacement_manifest.csv",
    )
    parser.add_argument(
        "--review-template",
        type=Path,
        default=project_root
        / "reports/manual_review/semantic_independent_eval_v1_repaired_review_template.csv",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=project_root / "reports/data_audit_semantic_gold_v1_repaired",
    )
    parser.add_argument("--similarity-threshold", type=float, default=0.55)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = run_repair(
            args.project_root,
            args.original,
            args.sanitize_audit,
            args.trial_review,
            args.output,
            args.manifest,
            args.review_template,
            args.report_dir,
            args.similarity_threshold,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        "repaired independent evaluation candidates written: "
        f"replacements={summary['replacement_count']}, "
        f"retained={summary['retained_count']}, "
        f"audit_passed={summary['audit_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import type { ImageAsset, Platform, SourceMaterial } from "../shared/types";

const DASHSCOPE_IMAGE_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis";
const DASHSCOPE_TASK_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/tasks";
const IMAGE_TIMEOUT_MS = 90000;
const VOLCANO_IMAGE_BASE = "https://ark.cn-beijing.volces.com/api/v3";

export interface PlatformVisualSpec {
  platform: Platform;
  coverAspectRatio: string;
  inlineAspectRatio: string;
  imageCount: number;
  styleGuide: string;
}

export const PLATFORM_VISUAL_SPECS: Record<Platform, PlatformVisualSpec> = {
  wechat: {
    platform: "wechat",
    coverAspectRatio: "2.35:1",
    inlineAspectRatio: "16:9",
    imageCount: 3,
    styleGuide:
      "公众号以长图文阅读为主：封面必须清晰、有主题主体，正文每2-3个小节插入一张解释型或案例型图片，避免花哨拼贴。"
  },
  xiaohongshu: {
    platform: "xiaohongshu",
    coverAspectRatio: "3:4",
    inlineAspectRatio: "3:4",
    imageCount: 5,
    styleGuide:
      "小红书以移动瀑布流和多图卡片为主：首图必须有强标题感，后续图片适合做清单、步骤、对比、避坑卡片，视觉要轻快但信息密度高。"
  },
  toutiao: {
    platform: "toutiao",
    coverAspectRatio: "16:9",
    inlineAspectRatio: "16:9",
    imageCount: 3,
    styleGuide:
      "今日头条以信息流推荐和快速扫读为主：封面要直观可信，正文图片服务事实解释和案例佐证，避免过度设计感。"
  }
};

export async function preparePlatformImages(
  topic: string,
  platform: Platform,
  sources: SourceMaterial[],
  prompts: string[]
): Promise<ImageAsset[]> {
  const spec = PLATFORM_VISUAL_SPECS[platform];
  const sourceImages = collectSourceImages(sources, platform, spec).slice(0, spec.imageCount);
  if (sourceImages.length >= spec.imageCount) {
    return sourceImages;
  }

  const generated = await generateMissingImages(topic, platform, spec, prompts, spec.imageCount - sourceImages.length);
  return [...sourceImages, ...generated].slice(0, spec.imageCount);
}

export function buildPlatformImagePrompts(topic: string, platform: Platform) {
  const spec = PLATFORM_VISUAL_SPECS[platform];
  if (platform === "wechat") {
    return [
      `${topic}，公众号封面，${spec.coverAspectRatio}，真实新闻编辑部场景，键盘纸张咖啡，克制专业质感，适合新媒体长文${NO_TEXT_RULE}`,
      `${topic}，正文解释配图，${spec.inlineAspectRatio}，流程图式构图，抽象数据可视化，干净背景，适合段落插图${NO_TEXT_RULE}`,
      `${topic}，案例对比图，${spec.inlineAspectRatio}，左右对比构图，真实场景摄影，理性可信，移动端友好${NO_TEXT_RULE}`
    ];
  }
  if (platform === "xiaohongshu") {
    return [
      `${topic}，小红书首图封面，${spec.coverAspectRatio}，明亮柔和色调，干净留白构图，视觉焦点明确，适合手机瀑布流${NO_TEXT_RULE}`,
      `${topic}，小红书信息卡片，${spec.inlineAspectRatio}，图形化信息展示，简约插画风格，色彩轻快${NO_TEXT_RULE}`,
      `${topic}，小红书对比卡片，${spec.inlineAspectRatio}，左右对比构图，简约视觉风格，色块分区清晰${NO_TEXT_RULE}`
    ];
  }
  return [
    `${topic}，今日头条信息流封面，${spec.coverAspectRatio}，新闻感、真实场景、主体明确、移动端缩略图清楚${NO_TEXT_RULE}`,
    `${topic}，头条正文配图，${spec.inlineAspectRatio}，真实场景加数据图表，可信、克制、适合资讯文章${NO_TEXT_RULE}`,
    `${topic}，头条案例解释图，${spec.inlineAspectRatio}，普通读者能一眼理解的现实场景${NO_TEXT_RULE}`
  ];
}

function collectSourceImages(
  sources: SourceMaterial[],
  platform: Platform,
  spec: PlatformVisualSpec
): ImageAsset[] {
  const seen = new Set<string>();
  return sources
    .flatMap((source) => source.images ?? [])
    .filter((image) => image.url && !seen.has(image.url) && seen.add(image.url))
    .map((image, index) => ({
      ...image,
      id: image.id || `source-image-${index + 1}`,
      platform,
      aspectRatio: image.aspectRatio || spec.inlineAspectRatio,
      placement: index === 0 ? "cover" : `inline-${index}`
    }));
}

const NO_TEXT_RULE = " CRITICAL: The image MUST NOT contain ANY text, Chinese characters, English words, numbers, titles, or captions. Pure visual scene with no text or writing of any kind whatsoever. NO TEXT ALLOWED IN THE IMAGE.";

async function generateMissingImages(
  topic: string,
  platform: Platform,
  spec: PlatformVisualSpec,
  prompts: string[],
  count: number
): Promise<ImageAsset[]> {
  const volcanoApiKey = process.env.VOLCANO_IMAGE_API_KEY;
  const volcanoEndpoint = process.env.VOLCANO_IMAGE_ENDPOINT;
  const useVolcano = !!(volcanoApiKey && volcanoEndpoint);
  const dashScopeApiKey = process.env.ALI_BAILIAN_API_KEY || process.env.DASHSCOPE_API_KEY;
  if ((!useVolcano && !dashScopeApiKey) || count <= 0) {
    return prompts.slice(0, count).map((prompt, index) => fallbackImage(topic, platform, spec, prompt, index));
  }

  const generated: ImageAsset[] = [];
  for (let index = 0; index < count; index += 1) {
    const prompt = prompts[index % prompts.length];
    const aspectRatio = index === 0 ? spec.coverAspectRatio : spec.inlineAspectRatio;
    try {
      let url: string;
      if (useVolcano) {
        url = await generateVolcanoImage(volcanoApiKey, volcanoEndpoint, prompt, aspectRatio);
      } else {
        url = await generateDashScopeImage(dashScopeApiKey, prompt, imageSizeForAspectRatio(aspectRatio));
      }
      generated.push({
        id: `generated-${platform}-${index + 1}-${Date.now()}`,
        title: `${platform} 生成图 ${index + 1}`,
        url,
        origin: "generated",
        prompt,
        platform,
        aspectRatio,
        placement: index === 0 ? "cover" : `inline-${index}`
      });
    } catch (error) {
      generated.push({
        ...fallbackImage(topic, platform, spec, prompt, index),
        title: `${platform} 生成图失败 ${index + 1}`,
        sourceUrl: `local://image-generation-error/${encodeURIComponent(error instanceof Error ? error.message : "unknown")}`
      });
    }
  }
  return generated;
}

function fallbackImage(topic: string, platform: Platform, spec: PlatformVisualSpec, prompt: string, index: number): ImageAsset {
  return {
    id: `image-prompt-${platform}-${index + 1}-${hash(prompt)}`,
    title: `${topic} 图片生成提示 ${index + 1}`,
    origin: "generated",
    prompt,
    platform,
    aspectRatio: index === 0 ? spec.coverAspectRatio : spec.inlineAspectRatio,
    placement: index === 0 ? "cover" : `inline-${index}`
  };
}

async function generateDashScopeImage(apiKey: string, prompt: string, size: string) {
  const taskResponse = await fetch(DASHSCOPE_IMAGE_ENDPOINT, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
      "X-DashScope-Async": "enable"
    },
    body: JSON.stringify({
      model: process.env.ALI_IMAGE_MODEL || "wanx2.1-t2i-turbo",
      input: { prompt },
      parameters: {
        size,
        n: 1
      }
    })
  });

  if (!taskResponse.ok) {
    throw new Error(`DashScope image task failed: ${taskResponse.status} ${await taskResponse.text()}`);
  }

  const taskData = (await taskResponse.json()) as { output?: { task_id?: string }; message?: string };
  const taskId = taskData.output?.task_id;
  if (!taskId) {
    throw new Error(taskData.message || "DashScope did not return task_id");
  }

  const deadline = Date.now() + IMAGE_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    const response = await fetch(`${DASHSCOPE_TASK_ENDPOINT}/${taskId}`, {
      headers: { Authorization: `Bearer ${apiKey}` }
    });
    if (!response.ok) {
      throw new Error(`DashScope image poll failed: ${response.status} ${await response.text()}`);
    }
    const data = (await response.json()) as {
      output?: { task_status?: string; results?: Array<{ url?: string }> };
      message?: string;
    };
    if (data.output?.task_status === "SUCCEEDED") {
      const url = data.output.results?.[0]?.url;
      if (!url) {
        throw new Error("DashScope image result missing url");
      }
      return url;
    }
    if (data.output?.task_status === "FAILED" || data.output?.task_status === "UNKNOWN") {
      throw new Error(data.message || `DashScope task ${data.output.task_status}`);
    }
  }
  throw new Error("DashScope image generation timed out");
}

async function generateVolcanoImage(apiKey: string, endpoint: string, prompt: string, aspectRatio: string): Promise<string> {
  /** Generate image via Volcano Engine ARK /v3/images/generations (OpenAI-compatible).
   *  Returns the image URL directly (synchronous, no polling needed).
   *  Volcano requires at least 3686400 pixels per image.
   */
  const size = volcanoImageSize(aspectRatio);
  const response = await fetch(`${VOLCANO_IMAGE_BASE}/images/generations`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model: endpoint,
      prompt,
      n: 1,
      size
    })
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Volcano image task failed: ${response.status} ${text}`);
  }

  const data = (await response.json()) as { data?: Array<{ url?: string }> };
  const url = data.data?.[0]?.url;
  if (!url) {
    throw new Error("Volcano image result missing url");
  }
  return url;
}

function volcanoImageSize(aspectRatio: string): string {
  /** Return a size >= 3686400 pixels matching the aspect ratio.
   *  Format: "WxH" (OpenAI-compatible, volcano uses x not dashscope's *)
   */
  if (aspectRatio === "3:4") return "1920x2560";
  if (aspectRatio === "2.35:1") return "2944x1253";
  return "2560x1440"; // 16:9
}

function imageSizeForAspectRatio(aspectRatio: string) {
  if (aspectRatio === "3:4") {
    return "768*1024";
  }
  if (aspectRatio === "2.35:1") {
    return "1280*720";
  }
  return "1280*720";
}

function hash(value: string) {
  let result = 0;
  for (let index = 0; index < value.length; index += 1) {
    result = (result * 31 + value.charCodeAt(index)) >>> 0;
  }
  return result.toString(36);
}

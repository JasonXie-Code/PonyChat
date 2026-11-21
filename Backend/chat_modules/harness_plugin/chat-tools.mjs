// Trusted, per-turn capability bridge. No filesystem, shell, or user-selectable scope.
import { Buffer } from 'node:buffer';
export const name = 'ponychat-chat-tools';
export const inject = ['tools', 'attachments'];
export function apply(ctx, config) {
  for (const tool of config.tools) {
    ctx.tools.register({
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
      output: {
        schema: ['read_history_image', 'read_web_image'].includes(tool.name) ? { type: 'object' } : { type: 'string' },
        render: (_args, value) => {
          if (['read_history_image', 'read_web_image'].includes(tool.name)) {
            const result = value;
            if (Array.isArray(result.content)) return result.content;
            return [{ type: 'text', text: JSON.stringify(result) }];
          }
          return [{ type: 'text', text: value }];
        },
      },
      async execute(args, exec) {
        if (!args || typeof args !== 'object' || Array.isArray(args)) {
          throw new Error('Tool arguments must be an object.');
        }
        const sessionId = config.sessionRouting ? exec.agent?.id : undefined;
        if (config.sessionRouting && typeof sessionId !== 'string') {
          throw new Error('Missing trusted Agent session.');
        }
        const response = await fetch(config.endpoint + '/' + tool.name, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + process.env.PONYCHAT_HARNESS_TOKEN,
            'Content-Type': 'application/json',
            ...(config.sessionRouting ? { 'X-PonyChat-Session': sessionId } : {}) },
          body: JSON.stringify(args), signal: exec.signal,
        });
        if (!response.ok) {
          if (response.status === 409) {
            const failure = await response.json();
            if (failure.code === 'tool_budget_exhausted') {
              throw new Error('Tool budget exhausted for this turn. This is not provider rate limiting. Do not retry; finish with needs_more=true and leave remaining work for the next turn.');
            }
          }
          if (response.status === 422) {
            const validation = await response.json();
            if (typeof validation.error === 'string') {
              throw new Error('Invalid tool arguments: ' + validation.error.slice(0, 500));
            }
          }
          throw new Error('Chat capability failed: HTTP ' + response.status);
        }
        const result = await response.json();
        const budget = result.budget;
        const reminder = budget && Number.isInteger(budget.remaining)
          ? '\n[Tool budget: ' + budget.remaining + ' calls remaining in this turn. '
            + (budget.remaining === 0 ? 'Do not call more tools; finish now and report any remaining work.'
              : 'Reserve calls for required writes before starting more work.') + ']'
          : '';
        if (['read_history_image', 'read_web_image'].includes(tool.name)) {
          const content = result.value?.content;
          if (!Array.isArray(content)) return result.value;
          // Tool renderers require admitted attachment references, unlike the
          // SDK prompt API, which admits base64 image inputs automatically.
          const images = content.filter(part => part.type === 'image');
          const refs = await ctx.attachments.saveImages(images.map(part => ({
            data: Buffer.from(part.data, 'base64'), mediaType: part.mimeType,
          })));
          let index = 0;
          return { content: [...content.map(part => part.type === 'image'
            ? { type: 'image', attachment: refs[index++] } : part),
            { type: 'text', text: reminder }] };
        }
        return JSON.stringify(result.value) + reminder;
      },
    });
  }
}

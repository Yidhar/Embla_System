import MarkdownIt from 'markdown-it'

const md = new MarkdownIt()

export function render(content: string) {
  return md.render(content)
}

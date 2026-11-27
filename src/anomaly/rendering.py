"""Render untrusted notification text with a small HTML allowlist."""

import markdown
import nh3
from markupsafe import Markup


def render_description(description):
    html = markdown.markdown(description or '')
    cleaned = nh3.clean(
        html,
        tags={'p', 'br', 'a', 'strong', 'em', 'b', 'i', 'ul', 'ol', 'li',
              'blockquote', 'code', 'pre', 'hr', 'sub', 'sup'},
        attributes={'a': {'href', 'title'}},
        url_schemes={'http', 'https'},
        link_rel='noopener noreferrer',
    )
    # Only sanitized fragments acquire the safe marker; templates autoescape
    # plain strings instead of unconditionally trusting the database field.
    return Markup(cleaned)

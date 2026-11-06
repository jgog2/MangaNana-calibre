"""Local-render ownership, intentionally separate from acquisition request IDs."""
from dataclasses import dataclass


@dataclass
class RenderOwnership:
    generation: int = 0

    def advance(self):
        self.generation += 1
        return self.generation

    def accepts(self, token):
        return token == self.generation

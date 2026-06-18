package screenbot

import (
	"fmt"
	"math"
	"math/rand/v2"
)

// Action is a unit of automation that may fail.
type Action func() error

// WeightedAction associates an action with its percentage chance of running.
type WeightedAction struct {
	Name    string
	Percent float64
	Action  Action
}

// Percent creates an unnamed weighted action.
func Percent(chance float64, action Action) WeightedAction {
	return WeightedAction{Percent: chance, Action: action}
}

// NamedPercent creates a weighted action whose name is included in errors.
func NamedPercent(name string, chance float64, action Action) WeightedAction {
	return WeightedAction{Name: name, Percent: chance, Action: action}
}

// RunWeightedAction randomly selects and runs exactly one action. Percentages
// must be non-negative and total 100.
func RunWeightedAction(actions ...WeightedAction) (int, error) {
	if err := validateWeightedActions(actions); err != nil {
		return -1, err
	}
	total := 0.0
	for _, action := range actions {
		total += action.Percent
	}
	index := pickWeightedAction(actions, rand.Float64()*total)
	if err := actions[index].Action(); err != nil {
		if actions[index].Name != "" {
			return index, fmt.Errorf("weighted action %q: %w", actions[index].Name, err)
		}
		return index, fmt.Errorf("weighted action %d: %w", index, err)
	}
	return index, nil
}

func validateWeightedActions(actions []WeightedAction) error {
	if len(actions) < 2 {
		return fmt.Errorf("at least two weighted actions are required")
	}
	total := 0.0
	for i, action := range actions {
		if action.Action == nil {
			return fmt.Errorf("weighted action %d has no function", i)
		}
		if math.IsNaN(action.Percent) || math.IsInf(action.Percent, 0) || action.Percent < 0 || action.Percent > 100 {
			return fmt.Errorf("weighted action %d percentage must be between 0 and 100", i)
		}
		total += action.Percent
	}
	if math.Abs(total-100) > 1e-9 {
		return fmt.Errorf("weighted action percentages must total 100, got %.10g", total)
	}
	return nil
}

func pickWeightedAction(actions []WeightedAction, roll float64) int {
	cumulative := 0.0
	for i, action := range actions {
		cumulative += action.Percent
		if roll < cumulative {
			return i
		}
	}
	// Validation guarantees a total of 100. This handles floating-point edges.
	return len(actions) - 1
}

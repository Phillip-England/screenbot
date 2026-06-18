package screenbot

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
)

type CoordinateBook struct {
	Path   string
	Points map[string]Point
}

func NewCoordinateBook(path string) (*CoordinateBook, error) {
	b := &CoordinateBook{Path: path, Points: make(map[string]Point)}
	if _, err := os.Stat(path); err == nil {
		return b, b.Load()
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	return b, nil
}

func (b *CoordinateBook) Set(name string, point Point) *CoordinateBook {
	b.Points[name] = point
	return b
}
func (b *CoordinateBook) SetCurrent(name string) error {
	p, err := MousePosition()
	if err != nil {
		return err
	}
	b.Set(name, p)
	return nil
}
func (b *CoordinateBook) Get(name string) (Point, error) {
	p, ok := b.Points[name]
	if !ok {
		return Point{}, fmt.Errorf("no coordinate named %q", name)
	}
	return p, nil
}
func (b *CoordinateBook) Delete(name string) *CoordinateBook { delete(b.Points, name); return b }
func (b *CoordinateBook) Names() []string {
	names := make([]string, 0, len(b.Points))
	for name := range b.Points {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}
func (b *CoordinateBook) Load() error {
	data, err := os.ReadFile(b.Path)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, &b.Points)
}
func (b *CoordinateBook) Save() error {
	data, err := json.MarshalIndent(b.Points, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return os.WriteFile(b.Path, data, 0o644)
}
func (b *CoordinateBook) Click(name string, options ClickOptions) (Point, error) {
	p, err := b.Get(name)
	if err != nil {
		return Point{}, err
	}
	return Click(p, options)
}
func (b *CoordinateBook) MoveTo(name string, options MoveOptions) (Point, error) {
	p, err := b.Get(name)
	if err != nil {
		return Point{}, err
	}
	return MoveTo(p, options)
}

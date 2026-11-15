# C4InterFlow (C# .NET 8)
**Source :** C4InterFlow.zip → C4InterFlow-master/
**Language :** C# .NET 8
**Compilation :** `dotnet build C4InterFlow.sln`

## Assemblies extraits

| Assembly | Dossier | Rôle |
|---------|---------|------|
| `C4InterFlow` | `csharp/C4InterFlow/` | Core : types, attributs, abstractions AaC |
| `C4InterFlow.Automation` | `csharp/C4InterFlow.Automation/` | Readers (C#, YAML, JSON) et Writers (C#, YAML, JSON, CSV) |
| `C4InterFlow.Cli` | `csharp/C4InterFlow.Cli/` | Point d'entrée CLI (`Program.cs`) |

## Classes C# clés

```csharp
// C4InterFlow/Automation/AaCReaderContext.cs
public class AaCReaderContext {
    public static AaCReaderContext GetInstance();
    public void SetCurrentStrategy(AaCReaderStrategy strategy,
        string[] inputPaths, string[] viewsPaths, string[] parameters);
    public IAaCReader GetAaCReader(string? alias = null);
}

// C4InterFlow/Automation/AaCWriterContext.cs
public class AaCWriterContext {
    public AaCWriterContext(AaCWriterStrategy strategy,
        string namespaceName, string outputPath, string[] parameters);
    public void ExecuteStrategy();
}

// C4InterFlow.Automation/Readers/CSharpAaCReaderStrategy.cs
public class CSharpAaCReaderStrategy : AaCReaderStrategy {
    public override SoftwareSystem[] GetSoftwareSystems();
    public override Container[] GetContainers(string systemAlias);
    public override Component[] GetComponents(string containerAlias);
    public override Flow[] GetFlows(string componentAlias);
}

// C4InterFlow.Automation/Readers/YamlAaCReaderStrategy.cs
public class YamlAaCReaderStrategy : AaCReaderStrategy {
    // Lit AaC depuis fichiers YAML
}

// C4InterFlow.Automation/Writers/CSharpToCSharpAaCWriter.cs
public class CSharpToCSharpAaCWriter {
    public void Write(SoftwareSystem[] systems, string outputPath);
}
```

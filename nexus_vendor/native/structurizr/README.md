# Structurizr DSL (Java)
**Source :** dsl.zip → dsl-master/src/main/java/com/structurizr/dsl/
**Language :** Java 11+
**Build :** `./gradlew build` ou `mvn package`
**JAR CLI :** https://github.com/structurizr/cli/releases

## Fichiers Java extraits (86 fichiers — parseurs DSL complets)

| Parseur | Rôle |
|---------|------|
| `WorkspaceParser.java` | Parser principal. `parseWorkspace(content)` → dispatch aux sous-parseurs |
| `SoftwareSystemParser.java` | `parseSoftwareSystem(tokens, ctx)` → `SoftwareSystem` |
| `ContainerParser.java` | `parseContainer(tokens, ctx)` → `Container` dans un SoftwareSystem |
| `ComponentParser.java` | `parseComponent(tokens, ctx)` → `Component` dans un Container |
| `PersonParser.java` | `parsePerson(tokens, ctx)` → `Person` (acteur humain) |
| `RelationshipParser.java` | `parseRelationship(tokens, ctx)` → relation entre éléments |
| `DeploymentEnvironmentParser.java` | `parseDeploymentEnvironment(tokens, ctx)` → env de déploiement |
| `DeploymentNodeParser.java` | `parseDeploymentNode(tokens, ctx)` → nœud de déploiement |
| `SystemLandscapeViewParser.java` | Vue système landscape |
| `SystemContextViewParser.java` | Vue système context |
| `ContainerViewParser.java` | Vue conteneur |
| `ComponentViewParser.java` | Vue composant |
| `DeploymentViewParser.java` | Vue déploiement |
| `AutoLayoutParser.java` | `parseAutoLayout(tokens, ctx)` → configure auto-layout (Dagre) |
| `IncludeParser.java` | `parseInclude(tokens, ctx)` → inclusion de fichiers DSL externes |
| `ElementStyleParser.java` | Styles visuels des éléments |
| `RelationshipStyleParser.java` | Styles visuels des relations |
| `DslContext.java` | Contexte de parsing partagé (variables, stack) |
| `AbstractParser.java` | Classe de base de tous les parseurs |
| `FileUtils.java` | `readLine(content, lineNumber)`, `readLines(content)` |

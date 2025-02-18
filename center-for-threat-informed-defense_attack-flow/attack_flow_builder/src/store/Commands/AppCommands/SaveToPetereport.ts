import Configuration from "@/assets/configuration/builder.config";
import { AppCommand } from "../AppCommand";
import { ApplicationStore } from "@/store/StoreTypes";
import { Browser } from "@/assets/scripts/Browser";
import { PageImage } from "@/assets/scripts/BlockDiagram/PageImage";

export class SaveToPetereport extends AppCommand {

    /**
     * Saves a page to the Petereport Web Application.
     * @param context
     *  The application context.
     */
    constructor(context: ApplicationStore) {
        super(context);
    }


    /**
     * Executes the command.
     */

    public execute(): void {
            let editor = this._context.activePage;
            let d = this._context.settings.view.diagram;         
            let e = this._context.settings.file.image_export;
            let image = new PageImage(
                editor.page,
                e.padding,
                d.display_grid,
                d.display_shadows,
                d.display_debug_mode
            );
            Browser.downloadTextPetereport(
                editor.page.props.toString(),
                editor.toFile(),
                Configuration.file_type_extension,
                image.capture()
            );
        }
}
